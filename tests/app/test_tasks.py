"""Task 4.2 — the worker jobs (Procrastinate). Jobs are REFERENCES (a ulid), never payloads:
execution re-reads canonical truth and recomputes (ADR 0014). These tests drive Procrastinate's
``InMemoryConnector`` so no live worker/broker is needed, and run one job through the real task
function to prove the reference semantics and a synchronous worker-execution smoke.
"""

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image
from procrastinate.testing import InMemoryConnector

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import thumbnail_path
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

_MIRROR = "http://mirror.example/dav/"


@pytest.fixture
def store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0, changed_by="tester")
    collections.save(
        Collection(
            ulid="FOTOS", name="Fotos", parent_id="ROOT", audience=Audience(AudienceTier.PUBLIC)
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(ulid="01FOTO", title="Foto", collection_id="FOTOS", lifecycle=Lifecycle.PUBLISHED),
        0,
        changed_by="tester",
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
        changed_by="tester",
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
    """The Procrastinate thumbnail task is a reference over an Article's ulid and a content-hash: it
    re-reads the file from the store the factory builds and writes the WebP into the configured
    THUMBNAIL_ROOT. Runs the task's underlying function directly (no DB needed)."""
    import bundesarchiv.app.tasks as tasks_mod

    store = InMemoryObjectStore()
    articles = ArticleRepository(store)
    ref = articles.add_media("A1", "p.png", io.BytesIO(_png_bytes()), media_type="image/png")
    articles.save(Article("A1", "Bild", "FOTOS", media=(ref,)), 0, changed_by="tester")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    thumbs = tmp_path / "thumbs"
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        tasks_mod.generate_thumbnail.func(ulid="A1", content_hash=ref.content_hash)
    out = thumbnail_path(thumbs, ref.content_hash)
    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "WEBP"


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (50, 100, 150)).save(buf, format="PNG")
    return buf.getvalue()


def test_the_monthly_verify_fails_its_job_when_it_finds_something(tmp_path: Path) -> None:
    """A finding must not pass as a finished job: the job fails, so it shows among the failed
    ones."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path)):
        Archive.canonical().store.write_atomic("articles/01WAISE/media/Scan.pdf", b"Scan")
        with pytest.raises(CommandError, match="Befunde"):
            tasks_mod.verify.func(timestamp=0)


# ---------------------------------------------------------------------------
# Task 4.9 — WebDAV mirror replay + reconcile (jobs are references)
# ---------------------------------------------------------------------------


def test_mirror_store_is_none_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The common dev case: BUNDESARCHIV_MIRROR_DAV_URL unset -> no mirror store is built, so every
    mirror job is a clean no-op (the mirror is optional convenience, never required)."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        assert tasks_mod.mirror_store() is None


@pytest.mark.django_db
def test_the_push_job_pushes_the_saved_record_and_notes_it(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.app.push_record import PostgresPushRecord

    remote = InMemoryObjectStore()
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: remote)

    tasks_mod.mirror_push.func(ulid="01FOTO")

    (readme,) = (key.key for key in ArticleRepository(store).keys_for("01FOTO"))
    assert remote.read(readme) == store.read(readme)
    assert PostgresPushRecord().held([readme]).keys() == {readme}


def test_mirror_push_task_is_noop_when_mirror_unset(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No mirror configured -> the job returns for a saved Article without touching anything: no
    remote, no push record (this test has no database)."""
    import bundesarchiv.app.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: None)

    tasks_mod.mirror_push.func(ulid="01FOTO")


@pytest.mark.django_db
def test_the_reconcile_job_returns_how_many_keys_each_finding_holds(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    remote = InMemoryObjectStore()
    remote.write_atomic("Notizen/liste.txt", b"not the app's")
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: remote)

    counts = tasks_mod.mirror_reconcile.func()

    assert counts == {
        "sent": len(list(store.list())),
        "recorded": 0,
        "changed": 0,
        "mismatched": 0,
        "unreadable": 0,
        "remote_only": 1,
        "failed": 0,
    }


def test_mirror_reconcile_task_is_noop_when_mirror_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No mirror configured -> the reconcile is a clean no-op that says it skipped."""
    import bundesarchiv.app.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "canonical_store", InMemoryObjectStore)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: None)

    assert tasks_mod.mirror_reconcile.func() == {"skipped": True}


def _queued(enqueue: Callable[[], None], *, mirror: str | None) -> list[tuple[str, str]]:
    """The (task, ulid) of every job ``enqueue`` queues with the system of record at ``mirror``."""
    from procrastinate.contrib.django import app

    connector = InMemoryConnector()
    with (
        override_settings(
            BUNDESARCHIV_MIRROR_DAV_URL=mirror,
            BUNDESARCHIV_MIRROR_DAV_USER="u",
            BUNDESARCHIV_MIRROR_DAV_PASSWORD="p",
        ),
        app.replace_connector(connector),
    ):
        enqueue()
    return [(job["task_name"], job["args"]["ulid"]) for job in connector.jobs.values()]


def test_enqueue_mirror_push_is_noop_when_mirror_unset() -> None:
    """No queue churn for a feature that is off."""
    import bundesarchiv.app.tasks as tasks_mod

    assert _queued(lambda: tasks_mod.enqueue_mirror_push("01A"), mirror=None) == []


def test_enqueue_mirror_push_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """GH #20: the enqueue path must answer "is mirroring on" from settings alone — it must never
    construct a fresh ``httpx2.Client`` (eager SSL-context load) just to throw it away. Only
    ``mirror_push`` itself, once actually run, may build one."""
    import httpx2

    import bundesarchiv.app.tasks as tasks_mod

    def _boom(*_args: object, **_kw: object) -> None:
        raise AssertionError("client built on enqueue path")

    # Patch the shared ``httpx2`` module object tasks.py imported (``import httpx2``, not
    # ``from httpx2 import Client``) — this attribute IS what ``tasks.mirror_store`` calls.
    monkeypatch.setattr(httpx2, "Client", _boom)

    queued = _queued(lambda: tasks_mod.enqueue_mirror_push("01A"), mirror=_MIRROR)
    assert queued == [("mirror_push", "01A")]


def test_saves_of_one_record_share_one_queued_push_and_never_hold_back_its_delete() -> None:
    """A push re-reads current truth when it runs, so one queued push per ulid covers every save
    until then; a hard delete is its own job."""
    import bundesarchiv.app.tasks as tasks_mod

    def saves_then_a_delete() -> None:
        tasks_mod.enqueue_mirror_push("01A")
        tasks_mod.enqueue_mirror_push("01A")
        tasks_mod.enqueue_mirror_push("01B")
        tasks_mod.enqueue_mirror_delete_article("01A")

    assert _queued(saves_then_a_delete, mirror=_MIRROR) == [
        ("mirror_push", "01A"),
        ("mirror_push", "01B"),
        ("mirror_delete_article", "01A"),
    ]


@pytest.mark.django_db(transaction=True)
def test_mirror_push_worker_execution_smoke(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker-loop smoke (like the reindex smoke): defer mirror_push onto the in-memory connector,
    drain the worker once, and the job pushes the Article end-to-end. ``transaction=True`` for the
    same reason as the reindex smoke: the job writes the push record in its own transaction."""
    import bundesarchiv.app.tasks as tasks_mod

    remote = InMemoryObjectStore()
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: remote)

    def defer() -> None:
        tasks_mod.mirror_push.defer(ulid="01FOTO")

    processed = tasks_mod.run_worker_once_in_test(defer=defer)

    assert list(remote.list()) == list(store.list("articles/"))
    assert processed >= 1


@pytest.mark.django_db(transaction=True)
def test_a_hard_delete_reaches_the_system_of_record_through_the_worker(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service enqueues the delete, the worker runs it: the Article's folder goes from the
    system of record, and its rows from the push record. ``transaction=True`` as in the push
    smoke."""
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.app.articles import hard_delete_article
    from bundesarchiv.app.push_record import PostgresPushRecord

    remote = InMemoryObjectStore()
    monkeypatch.setattr(tasks_mod, "canonical_store", lambda: store)
    monkeypatch.setattr(tasks_mod, "mirror_store", lambda: remote)
    tasks_mod.mirror_reconcile.func()

    def delete() -> None:
        archive = Archive.of(store)
        hard_delete_article(archive, "01FOTO", archive.articles.load("01FOTO").version)

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL="http://mirror.example/dav/"):
        tasks_mod.run_worker_once_in_test(defer=delete)

    assert list(remote.list()) == list(store.list())
    assert PostgresPushRecord().entries().keys() == set(store.list())
