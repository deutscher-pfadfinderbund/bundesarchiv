"""The worker jobs: references (a ulid), never payloads, so a run re-reads canonical (ADR 0014).
The task shells run over a canonical root on disk; the jobs over an in-memory archive."""

import contextlib
import io
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2
import pytest
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image
from tests._pdfs import text_pdf
from tests._queue import MIRROR, queued, run_worker_once_in_test

from bundesarchiv.app import jobs
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.push_record import InMemoryPushRecord, PostgresPushRecord
from bundesarchiv.app.thumbnails import thumbnail_path
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

ID_01A = ULID("01A")
ID_01FOTO = ULID("01FOTO")
ID_FOTOS = ULID("FOTOS")
ID_ROOT = ULID("ROOT")


def _seeded[S: ObjectStore](store: S) -> S:
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(
        Collection(ulid=ID_ROOT, name="Wurzel", parent_id=None), 0, changed_by="tester"
    )
    collections.save(
        Collection(
            ulid=ID_FOTOS,
            name="Fotos",
            parent_id=ID_ROOT,
            audience=Audience(AudienceTier.PUBLIC),
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(
            ulid=ID_01FOTO,
            title="Foto",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
        ),
        0,
        changed_by="tester",
    )
    return store


@pytest.fixture
def store() -> InMemoryObjectStore:
    return _seeded(InMemoryObjectStore())


@pytest.fixture
def canonical(tmp_path: Path) -> Iterator[ObjectStore]:
    """The seeded archive where the task shells find it: ``Archive.canonical()``."""
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        yield _seeded(Archive.canonical().store)


def _fake_dav(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[httpx2.Request], httpx2.Response]
) -> list[httpx2.Client]:
    """Every client ``tasks.mirror_store`` builds gets its answers from ``answer``, not the
    network; returns the clients built."""
    built: list[httpx2.Client] = []
    real = httpx2.Client

    def client(**kwargs: Any) -> httpx2.Client:
        made = real(transport=httpx2.MockTransport(answer), **kwargs)
        built.append(made)
        return made

    monkeypatch.setattr(httpx2, "Client", client)
    return built


@pytest.mark.django_db
def test_reindex_article_job_recomputes_from_current_canonical(canonical: ObjectStore) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    # (Job conceptually enqueued here for 01FOTO at PUBLIC.) Now canonical changes:
    articles = ArticleRepository(canonical)
    stored = articles.load(ID_01FOTO)
    articles.save(
        Article(
            ulid=ID_01FOTO,
            title="Foto",
            collection_id=ID_FOTOS,
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
def test_the_reconcile_job_logs_the_archive_stats_and_survives_their_failure(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from bundesarchiv.app import stats
    from bundesarchiv.index.models import ArticleIndex

    netted: list[Archive] = []
    with caplog.at_level("INFO", logger="bundesarchiv.app.stats"):
        jobs.reconcile(Archive.of(store), netted.append)
    assert [r.getMessage() for r in caplog.records] == ["archive stats"]
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    monkeypatch.setattr(stats, "log_archive_stats", lambda _: 1 / 0)
    jobs.reconcile(Archive.of(store), netted.append)
    assert len(netted) == 2  # the page-text net still ran


@pytest.mark.django_db
def test_reindex_subtree_job_recomputes_subtree(canonical: ObjectStore) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    tasks_mod.reindex_subtree.func(collection_ulid="FOTOS")
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"


@pytest.mark.django_db(transaction=True)
def test_worker_execution_smoke_runs_deferred_reindex_article(canonical: ObjectStore) -> None:
    """``transaction=True``: the worker commits the task's write in its own transaction, outside pytest-django's per-test rollback, so the row would leak into later tests."""
    from bundesarchiv.index.models import ArticleIndex

    result = run_worker_once_in_test(defer=lambda: enqueue_test_article())
    # After the one-shot drain, the deferred reindex_article has executed:
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
    assert result >= 1  # at least one job processed


def enqueue_test_article() -> None:
    """Helper the smoke test hands to the one-shot worker harness to defer a job in-test."""
    from bundesarchiv.app.tasks import reindex_article

    reindex_article.defer(ulid="01FOTO")


def test_generate_thumbnail_task_derives_from_canonical(tmp_path: Path) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    thumbs = tmp_path / "thumbs"
    with override_settings(
        BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical"),
        BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs),
    ):
        articles = Archive.canonical().articles
        ref = articles.add_media(
            ULID("A1"), "p.png", io.BytesIO(_png_bytes()), media_type="image/png"
        )
        articles.save(Article(ULID("A1"), "Bild", ID_FOTOS, media=(ref,)), 0, changed_by="tester")
        tasks_mod.generate_thumbnail.func(ulid="A1", content_hash=ref.content_hash)
    out = thumbnail_path(thumbs, ref.content_hash)
    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "AVIF"


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
        with pytest.raises(CommandError, match="Findings"):
            tasks_mod.verify.func(timestamp=0)


# ---------------------------------------------------------------------------
# The push to the system of record + reconcile
# ---------------------------------------------------------------------------


def test_mirror_store_is_none_when_url_unset() -> None:
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        assert tasks_mod.mirror_store() is None


def test_the_push_job_pushes_the_saved_record_and_notes_it(store: InMemoryObjectStore) -> None:
    remote, record = InMemoryObjectStore(), InMemoryPushRecord()

    jobs.mirror_push(Archive.of(store), remote, record, ID_01FOTO)

    (readme,) = (key.key for key in ArticleRepository(store).keys_for(ID_01FOTO))
    assert remote.read(readme) == store.read(readme)
    assert record.held([readme]).keys() == {readme}


def test_mirror_push_task_is_noop_when_mirror_unset() -> None:
    """No mirror configured -> the job returns without touching anything: no remote, no push
    record (this test has no database)."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        tasks_mod.mirror_push.func(ulid="01FOTO")


def test_the_reconcile_job_returns_how_many_keys_each_finding_holds(
    store: InMemoryObjectStore,
) -> None:
    remote = InMemoryObjectStore()
    remote.write_atomic("Notizen/liste.txt", b"not the app's")

    counts = jobs.mirror_reconcile(Archive.of(store), remote, InMemoryPushRecord())

    assert counts == {
        "sent": len(list(store.list())),
        "recorded": 0,
        "changed": 0,
        "mismatched": 0,
        "unreadable": 0,
        "remote_only": 1,
        "failed": 0,
    }


def test_mirror_reconcile_task_is_noop_when_mirror_unset() -> None:
    """No mirror configured -> the reconcile is a clean no-op that says it skipped."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        assert tasks_mod.mirror_reconcile.func() == {"skipped": True}


@pytest.mark.django_db
@pytest.mark.parametrize("status", [404, 500])
def test_a_mirror_task_closes_the_remote_it_built_whether_the_job_succeeds_or_fails(
    canonical: ObjectStore, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    built = _fake_dav(monkeypatch, lambda _request: httpx2.Response(status))
    fails = pytest.raises(ArchiveError) if status == 500 else contextlib.nullcontext()
    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=MIRROR), fails:
        tasks_mod.mirror_delete_article.func(ulid="01FOTO")

    (client,) = built
    assert client.is_closed


def test_enqueue_mirror_push_is_noop_when_mirror_unset() -> None:
    """No queue churn for a feature that is off."""
    import bundesarchiv.app.tasks as tasks_mod

    assert queued(lambda: tasks_mod.enqueue_mirror_push(ID_01A)) == []


def test_enqueue_mirror_push_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    def _boom(*_args: object, **_kw: object) -> None:
        raise AssertionError("client built on enqueue path")

    # Patch the shared ``httpx2`` module object tasks.py imported (``import httpx2``, not
    # ``from httpx2 import Client``) — this attribute IS what ``tasks.mirror_store`` calls.
    monkeypatch.setattr(httpx2, "Client", _boom)

    jobs = queued(lambda: tasks_mod.enqueue_mirror_push(ID_01A), mirror=True)
    assert jobs == [("mirror_push", {"ulid": "01A"})]


def test_saves_of_one_record_share_one_queued_push_and_never_hold_back_its_delete() -> None:
    """A push re-reads current truth when it runs, so one queued push per ulid covers every save
    until then; a hard delete is its own job."""
    import bundesarchiv.app.tasks as tasks_mod

    def saves_then_a_delete() -> None:
        tasks_mod.enqueue_mirror_push(ID_01A)
        tasks_mod.enqueue_mirror_push(ID_01A)
        tasks_mod.enqueue_mirror_push(ULID("01B"))
        tasks_mod.enqueue_mirror_delete_article(ID_01A)

    assert queued(saves_then_a_delete, mirror=True) == [
        ("mirror_push", {"ulid": "01A"}),
        ("mirror_push", {"ulid": "01B"}),
        ("mirror_delete_article", {"ulid": "01A"}),
    ]


@pytest.mark.django_db(transaction=True)
def test_a_hard_delete_reaches_the_system_of_record_through_the_worker(
    canonical: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service enqueues the delete, the worker runs it: the Article's folder goes from the
    system of record, and its rows from the push record. ``transaction=True`` as in the reindex
    smoke."""
    from bundesarchiv.app.articles import hard_delete_article

    archive = Archive.canonical()
    jobs.mirror_reconcile(archive, InMemoryObjectStore(), PostgresPushRecord())
    sent: list[tuple[str, str]] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append((request.method, request.url.path))
        if request.method == "PROPFIND":  # the folder is there
            return httpx2.Response(207, content=_collection(request.url.path))
        return httpx2.Response(204)

    _fake_dav(monkeypatch, answer)

    def delete() -> None:
        hard_delete_article(archive, ID_01FOTO, archive.articles.load(ID_01FOTO).version)

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=MIRROR):
        run_worker_once_in_test(defer=delete)

    folder = urlsplit(MIRROR).path + archive.articles.folder(ID_01FOTO)
    assert [path for method, path in sent if method == "DELETE"] == [folder]
    assert PostgresPushRecord().entries().keys() == set(canonical.list())


def _collection(path: str) -> bytes:
    """A WebDAV multistatus naming ``path`` as one collection."""
    return (
        f'<multistatus xmlns="DAV:"><response><href>{path}/</href><propstat><prop><resourcetype>'
        "<collection/></resourcetype></prop></propstat></response></multistatus>"
    ).encode()


def test_the_reconcile_job_logs_one_summary_record(
    store: InMemoryObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO", logger=jobs.__name__):
        counts = jobs.mirror_reconcile(
            Archive.of(store), InMemoryObjectStore(), InMemoryPushRecord()
        )

    (record,) = (r for r in caplog.records if r.name == jobs.__name__)
    fields = vars(record)
    assert (record.levelname, fields["task"], fields["outcome"]) == (
        "INFO",
        "mirror_reconcile",
        "ok",
    )
    assert fields["sent"] == counts["sent"] == len(list(store.list()))
    assert fields["sent_bytes"] == sum(len(store.read(key)) for key in store.list())
    assert fields["remote_keys"] == 0  # the listing before the push
    assert "remote_bytes" not in fields  # only a Nextcloud mirror answers
    assert fields["seconds"] >= 0


def test_a_failed_push_logs_its_summary_with_the_exception_class_and_still_raises(
    store: InMemoryObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken(InMemoryObjectStore):
        def create_large(self, key: str, stream: object, size: int) -> str:
            raise ArchiveError("down")

        def write_atomic(self, key: str, data: bytes) -> str:
            raise ArchiveError("down")

    with caplog.at_level("INFO", logger=jobs.__name__), pytest.raises(ArchiveError):
        jobs.mirror_push(Archive.of(store), Broken(), InMemoryPushRecord(), ID_01FOTO)

    (record,) = (r for r in caplog.records if r.name == jobs.__name__)
    fields = vars(record)
    assert (record.levelname, fields["outcome"], fields["exception_class"], fields["ulid"]) == (
        "ERROR",
        "failed",
        "ArchiveError",
        "01FOTO",
    )
    assert record.exc_info


@pytest.mark.django_db
def test_one_page_text_job_is_queued_per_article_that_misses_text_and_no_pdf_is_read(
    store: InMemoryObjectStore,
) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import MediaText

    articles = ArticleRepository(store)
    for ulid in ("01HEFT", "01ZWEI"):
        refs = tuple(
            articles.add_media(ULID(ulid), name, io.BytesIO(text_pdf([name])))
            for name in ("a.pdf", "b.pdf")
        )
        articles.save(Article(ULID(ulid), "Heft", ID_FOTOS, media=refs), 0, changed_by="tester")

    enqueue = lambda: tasks_mod.enqueue_missing_text(Archive.of(store))
    assert sorted(queued(enqueue), key=str) == [
        ("extract_media_text", {"ulid": "01HEFT"}),
        ("extract_media_text", {"ulid": "01ZWEI"}),
    ]
    assert MediaText.objects.count() == 0


@pytest.mark.django_db
def test_a_failed_page_text_enqueue_never_fails_the_rebuild(tmp_path: Path) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    store = LocalFsObjectStore(tmp_path)
    root = Collection(ulid=ID_ROOT, name="Wurzel", parent_id=None)
    CollectionRepository(store).save(root, 0, changed_by="tester")
    articles = ArticleRepository(store)
    heft = articles.add_media(ULID("01HEFT"), "a.pdf", io.BytesIO(text_pdf(["Lager"])))
    articles.save(Article(ULID("01HEFT"), "Heft", ID_ROOT, media=(heft,)), 0, changed_by="tester")

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path)):
        refuse = frozenset({"extract_media_text"})
        queued(lambda: tasks_mod.reconcile.func(timestamp=0), refuse=refuse)

    assert ArticleIndex.objects.filter(ulid="01HEFT").exists()


def test_a_page_text_job_already_queued_stands_in_for_the_next() -> None:
    import bundesarchiv.app.tasks as tasks_mod

    def two_saves() -> None:
        tasks_mod.enqueue_extract_media_text(ID_01A)
        tasks_mod.enqueue_extract_media_text(ID_01A)

    assert queued(two_saves) == [("extract_media_text", {"ulid": "01A"})]
