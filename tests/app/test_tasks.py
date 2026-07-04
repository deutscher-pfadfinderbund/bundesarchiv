"""Task 4.2 — the worker jobs (Procrastinate). Jobs are REFERENCES (a ulid), never payloads:
execution re-reads canonical truth and recomputes (ADR 0014). These tests drive Procrastinate's
``InMemoryConnector`` so no live worker/broker is needed, and run one job through the real task
function to prove the reference semantics and a synchronous worker-execution smoke.
"""

import pytest

from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository


@pytest.fixture
def store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0)
    collections.save(
        Collection(
            ulid="FOTOS", name="Fotos", parent_id="ROOT", audience=Audience(AudienceTier.PUBLIC)
        ),
        0,
    )
    articles.save(
        Article(ulid="01FOTO", title="Foto", collection_id="FOTOS", lifecycle=Lifecycle.PUBLISHED),
        0,
    )
    return store


@pytest.mark.django_db
def test_reindex_article_job_recomputes_from_current_canonical(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale-enqueued job, run AFTER a further edit, reflects CURRENT canonical (references, not
    payloads). We point the task's store factory at our in-memory store, then narrow the article
    between 'enqueue' and 'run'; running the task must produce the NARROWED scope."""
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)

    # (Job conceptually enqueued here for 01FOTO at PUBLIC.) Now canonical changes:
    articles = ArticleRepository(store)
    stored = articles.load("01FOTO")
    articles.save(
        Article(
            ulid="01FOTO",
            title="Foto",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.MEMBERS),  # narrowed after 'enqueue'
        ),
        stored.version,
    )

    # Run the task's underlying function directly (references recompute current truth).
    tasks_mod.reindex_article.func(ulid="01FOTO")

    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "MEMBERS"


@pytest.mark.django_db
def test_full_rebuild_job_rebuilds_everything(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    tasks_mod.full_rebuild.func()
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()


@pytest.mark.django_db
def test_reindex_subtree_job_recomputes_subtree(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    tasks_mod.reindex_subtree.func(collection_ulid="FOTOS")
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"


@pytest.mark.django_db
def test_worker_execution_smoke_runs_deferred_reindex_article(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker-loop smoke: defer reindex_article onto the in-memory connector, then drain the
    worker once (synchronous, one-shot). The job runs end-to-end and writes the index row."""
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    result = tasks_mod.run_worker_once_in_test(defer=lambda: enqueue_test_article())
    # After the one-shot drain, the deferred reindex_article has executed:
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
    assert result >= 1  # at least one job processed


def enqueue_test_article() -> None:
    """Helper the smoke test hands to the one-shot worker harness to defer a job in-test."""
    from bundesarchiv.app.tasks import reindex_article

    reindex_article.defer(ulid="01FOTO")
