"""Task 4.2 — the worker jobs (Procrastinate). Jobs are REFERENCES (a ulid), never payloads:
execution re-reads canonical truth and recomputes (ADR 0014). These tests drive Procrastinate's
``InMemoryConnector`` so no live worker/broker is needed, and run one job through the real task
function to prove the reference semantics and a synchronous worker-execution smoke.
"""

import io
from pathlib import Path

import pytest
from django.test import override_settings
from PIL import Image

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


@pytest.mark.django_db(transaction=True)
def test_worker_execution_smoke_runs_deferred_reindex_article(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker-loop smoke: defer reindex_article onto the in-memory connector, then drain the
    worker once (synchronous, one-shot). The job runs end-to-end and writes the index row.

    ``transaction=True``: the Procrastinate worker commits the task's DB write in its OWN
    transaction (outside pytest-django's per-test rollback), so the row would leak into later tests
    under the default rollback fixture; TransactionTestCase semantics truncate it after the test."""
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


def test_generate_thumbnail_task_derives_from_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Procrastinate thumbnail task is a reference over a content-hash: it re-reads the blob from
    the store the factory builds and writes the WebP into the configured THUMBNAIL_ROOT (a no-op for
    a hash with no blob). Runs the task's underlying function directly (no DB needed)."""
    import bundesarchiv.app.tasks as tasks_mod

    store = InMemoryObjectStore()
    ref = ArticleRepository(store).add_media("A1", "p.png", _png_bytes(), media_type="image/png")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    thumbs = tmp_path / "thumbs"
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        tasks_mod.generate_thumbnail.func(content_hash=ref.content_hash)
    out = thumbs / f"{ref.content_hash}.webp"
    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "WEBP"


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (50, 100, 150)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Task 4.9 — WebDAV mirror replay + reconcile (jobs are references)
# ---------------------------------------------------------------------------


def test_mirror_store_is_none_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The common dev case: BUNDESARCHIV_MIRROR_DAV_URL unset -> no mirror store is built, so every
    mirror job is a clean no-op (the mirror is optional convenience, never required)."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        assert tasks_mod.mirror_store() is None


def test_mirror_store_built_from_settings_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL set -> a WebDavObjectStore over an httpx client at the configured base_url + credentials."""
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore

    with override_settings(
        BUNDESARCHIV_MIRROR_DAV_URL="http://mirror.example/dav/",
        BUNDESARCHIV_MIRROR_DAV_USER="u",
        BUNDESARCHIV_MIRROR_DAV_PASSWORD="p",
    ):
        store = tasks_mod.mirror_store()
    assert isinstance(store, WebDavObjectStore)


def test_mirror_push_task_replays_key_to_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mirror_push reference job re-reads the CURRENT canonical bytes and writes to the mirror."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()
    mirror = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror)

    tasks_mod.mirror_push.func(key="articles/01A/README.md")

    assert mirror.read("articles/01A/README.md") == b"body"


def test_mirror_push_task_is_noop_when_mirror_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No mirror configured -> the job returns without touching anything (never raises)."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: None)

    tasks_mod.mirror_push.func(key="articles/01A/README.md")  # must not raise


def test_mirror_push_task_deletes_from_mirror_when_key_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reference semantics: a stale push whose key is gone from canonical deletes it from the mirror."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()  # key absent from canonical
    mirror = InMemoryObjectStore()
    mirror.write_atomic("articles/01A/README.md", b"leftover")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror)

    tasks_mod.mirror_push.func(key="articles/01A/README.md")

    assert not mirror.exists("articles/01A/README.md")


def test_mirror_reconcile_task_syncs_and_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reconcile job pushes missing + deletes stale and returns the summary counts as its
    result (pushed/deleted/failed) for the worker log."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()
    mirror = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"a")
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror)

    summary = tasks_mod.mirror_reconcile.func()

    assert mirror.read("articles/01A/README.md") == b"a"
    assert not mirror.exists("articles/01OLD/README.md")
    assert summary == {"pushed": 1, "deleted": 1, "failed": 0}


def test_mirror_reconcile_task_is_noop_when_mirror_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No mirror configured -> the reconcile is a clean no-op returning a zero/skipped summary."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"a")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: None)

    summary = tasks_mod.mirror_reconcile.func()

    assert summary == {"pushed": 0, "deleted": 0, "failed": 0, "skipped": True}


def test_mirror_push_task_closes_the_mirror_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """mirror_store() builds a fresh httpx.Client per job; the job must close it on completion so
    the connection pool never leaks, even though the push itself never raises."""
    import httpx

    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.app import mirror as mirror_mod
    from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore

    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")
    client = httpx.Client(base_url="http://mirror.invalid/")
    mirror_target = WebDavObjectStore(client)
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror_target)
    monkeypatch.setattr(mirror_mod, "push_key", lambda *_args, **_kw: None)

    tasks_mod.mirror_push.func(key="articles/01A/README.md")

    assert client.is_closed


def test_mirror_reconcile_task_closes_the_mirror_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same client-lifetime guarantee for the periodic reconcile sweep."""
    import httpx

    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.app import mirror as mirror_mod
    from bundesarchiv.app.mirror import ReconcileSummary
    from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore

    canonical = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")
    client = httpx.Client(base_url="http://mirror.invalid/")
    mirror_target = WebDavObjectStore(client)
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror_target)
    monkeypatch.setattr(
        mirror_mod,
        "reconcile",
        lambda *_args, **_kw: ReconcileSummary(pushed=0, deleted=0, failed=0),
    )

    tasks_mod.mirror_reconcile.func()

    assert client.is_closed


def test_enqueue_mirror_push_is_noop_when_mirror_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The enqueue wrapper the app services call: when the mirror is unset it must NOT defer a job
    (no queue churn for a feature that is off). Drives the real settings predicate (GH #20: the
    enqueue path no longer goes through ``mirror_store()`` at all)."""
    import bundesarchiv.app.tasks as tasks_mod

    deferred: list[str] = []
    monkeypatch.setattr(tasks_mod.mirror_push, "defer", lambda **kw: deferred.append(kw["key"]))

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        tasks_mod.enqueue_mirror_push("articles/01A/README.md")

    assert deferred == []


def test_enqueue_mirror_push_defers_when_mirror_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drives the real settings predicate (GH #20: the enqueue path no longer goes through
    ``mirror_store()`` at all — see ``test_enqueue_mirror_push_never_builds_a_client`` for the
    zero-client-construction pin)."""
    import bundesarchiv.app.tasks as tasks_mod

    deferred: list[str] = []
    monkeypatch.setattr(tasks_mod.mirror_push, "defer", lambda **kw: deferred.append(kw["key"]))

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL="http://mirror.example/dav/"):
        tasks_mod.enqueue_mirror_push("articles/01A/README.md")

    assert deferred == ["articles/01A/README.md"]


def test_enqueue_mirror_push_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """GH #20: the enqueue path must answer "is mirroring on" from settings alone — it must never
    construct a fresh ``httpx.Client`` (eager SSL-context load) just to throw it away. Only
    ``mirror_push`` itself, once actually run, may build one."""
    import httpx

    import bundesarchiv.app.tasks as tasks_mod

    def _boom(*_args: object, **_kw: object) -> None:
        raise AssertionError("client built on enqueue path")

    deferred: list[str] = []
    # Patch the shared ``httpx`` module object tasks.py imported (``import httpx``, not
    # ``from httpx import Client``) — this attribute IS what ``tasks.mirror_store`` calls.
    monkeypatch.setattr(httpx, "Client", _boom)
    monkeypatch.setattr(tasks_mod.mirror_push, "defer", lambda **kw: deferred.append(kw["key"]))

    with override_settings(
        BUNDESARCHIV_MIRROR_DAV_URL="http://mirror.example/dav/",
        BUNDESARCHIV_MIRROR_DAV_USER="u",
        BUNDESARCHIV_MIRROR_DAV_PASSWORD="p",
    ):
        tasks_mod.enqueue_mirror_push("articles/01A/README.md")

    assert deferred == ["articles/01A/README.md"]


@pytest.mark.django_db
def test_mirror_push_worker_execution_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker-loop smoke (like the reindex smoke): defer mirror_push onto the in-memory connector,
    drain the worker once, and the job replays the key to the mirror end-to-end."""
    import bundesarchiv.app.tasks as tasks_mod

    canonical = InMemoryObjectStore()
    mirror = InMemoryObjectStore()
    canonical.write_atomic("articles/01A/README.md", b"body")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: canonical)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: mirror)

    def defer() -> None:
        tasks_mod.mirror_push.defer(key="articles/01A/README.md")

    processed = tasks_mod.run_worker_once_in_test(defer=defer)

    assert mirror.read("articles/01A/README.md") == b"body"
    assert processed >= 1
