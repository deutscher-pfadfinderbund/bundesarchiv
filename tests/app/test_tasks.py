"""The worker jobs: references (a ulid), never payloads, so a run re-reads canonical (ADR 0014).
The task shells run over a canonical root on disk; the jobs over an in-memory archive."""

import contextlib
import io
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, get_args
from urllib.parse import urlsplit

import httpx2
import pytest
from django.core.management.base import CommandError
from django.test import override_settings
from PIL import Image
from tests._pdfs import text_pdf
from tests._queue import MIRROR, queued, queued_calls, run_worker_once_in_test

from bundesarchiv.app import jobs
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.jobs import (
    Job,
    MirrorDelete,
    MirrorPush,
    PageText,
    ReindexArticle,
    ReindexSubtree,
    Thumbnail,
)
from bundesarchiv.app.mirror import PushRecord
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


def _deps(
    store: ObjectStore, remote: ObjectStore | None, record: PushRecord | None = None
) -> jobs.Deps:
    """What the jobs work on: ``store`` as canonical, ``remote`` as the system of record."""
    return jobs.Deps(
        archive=Archive.of(store),
        thumbnail_root=Path("unused"),
        mirror=lambda: contextlib.nullcontext(remote),
        record=record or InMemoryPushRecord(),
    )


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

    articles = ArticleRepository(store)
    heft = articles.add_media(ULID("01HEFT"), "a.pdf", io.BytesIO(text_pdf(["Lager"])))
    articles.save(Article(ULID("01HEFT"), "Heft", ID_FOTOS, media=(heft,)), 0, changed_by="tester")
    netted: list[Job] = []
    with caplog.at_level("INFO", logger="bundesarchiv.app.stats"):
        jobs.reconcile(Archive.of(store), netted.append)
    assert "archive stats" in [r.getMessage() for r in caplog.records]
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    monkeypatch.setattr(stats, "log_archive_stats", lambda _: 1 / 0)
    jobs.reconcile(Archive.of(store), netted.append)
    assert netted == [PageText(ULID("01HEFT"))] * 2  # the page-text net still ran


@pytest.mark.django_db
def test_reindex_subtree_job_recomputes_subtree(canonical: ObjectStore) -> None:
    import bundesarchiv.app.tasks as tasks_mod
    from bundesarchiv.index.models import ArticleIndex

    tasks_mod.reindex_subtree.func(collection_ulid="FOTOS")
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"


@pytest.mark.django_db(transaction=True)
def test_worker_execution_smoke_runs_deferred_reindex_article(canonical: ObjectStore) -> None:
    """``transaction=True``: the worker commits the task's write in its own transaction, outside pytest-django's per-test rollback, so the row would leak into later tests."""
    from bundesarchiv.app.tasks import enqueue
    from bundesarchiv.index.models import ArticleIndex

    result = run_worker_once_in_test(defer=lambda: enqueue(ReindexArticle(ID_01FOTO)))
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
    assert result >= 1  # at least one job processed


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

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None), tasks_mod.mirror_store() as remote:
        assert remote is None


def test_the_push_job_pushes_the_saved_record_and_notes_it(store: InMemoryObjectStore) -> None:
    remote, record = InMemoryObjectStore(), InMemoryPushRecord()

    jobs.run(MirrorPush(ID_01FOTO, "article"), _deps(store, remote, record))

    (readme,) = (key.key for key in ArticleRepository(store).keys_for(ID_01FOTO))
    assert remote.read(readme) == store.read(readme)
    assert record.held([readme]).keys() == {readme}


@pytest.mark.django_db
@pytest.mark.parametrize(("ulid", "kind"), [(ID_01FOTO, "article"), (ID_FOTOS, "collection")])
def test_a_push_queued_before_it_carried_its_kind_still_pushes_its_record(
    canonical: ObjectStore, monkeypatch: pytest.MonkeyPatch, ulid: ULID, kind: str
) -> None:
    """Until it runs, its queueing lock holds back every later push of that record."""
    import bundesarchiv.app.tasks as tasks_mod

    put: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.method != "PUT":  # nothing is there yet
            return httpx2.Response(404)
        put.append(request.url.path)
        return httpx2.Response(201, headers={"ETag": '"pushed"'})

    _fake_dav(monkeypatch, answer)
    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=MIRROR):
        tasks_mod.mirror_push.func(ulid=ulid)

    archive = Archive.canonical()
    repository = archive.articles if kind == "article" else archive.collections
    assert put == [urlsplit(MIRROR).path + key.key for key in repository.keys_for(ulid)]


def test_mirror_push_task_is_noop_when_mirror_unset(canonical: ObjectStore) -> None:
    """No mirror configured -> the job returns without touching anything: no remote, no push
    record (this test has no database)."""
    import bundesarchiv.app.tasks as tasks_mod

    with override_settings(BUNDESARCHIV_MIRROR_DAV_URL=None):
        tasks_mod.mirror_push.func(ulid="01FOTO", kind="article")


def test_the_reconcile_job_returns_how_many_keys_each_finding_holds(
    store: InMemoryObjectStore,
) -> None:
    remote = InMemoryObjectStore()
    remote.write_atomic("Notizen/liste.txt", b"not the app's")

    counts = jobs.mirror_reconcile(
        Archive.of(store), remote, InMemoryPushRecord(), size=lambda: None
    )

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

    assert queued(lambda: tasks_mod.enqueue(MirrorPush(ID_01A, "article"))) == []


def test_enqueue_mirror_push_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    def _boom(*_args: object, **_kw: object) -> None:
        raise AssertionError("client built on enqueue path")

    # Patch the shared ``httpx2`` module object tasks.py imported (``import httpx2``, not
    # ``from httpx2 import Client``) — this attribute IS what ``tasks.mirror_store`` calls.
    monkeypatch.setattr(httpx2, "Client", _boom)

    push = MirrorPush(ID_01A, "article")
    assert queued(lambda: tasks_mod.enqueue(push), mirror=True) == [push]


def test_saves_of_one_record_share_one_queued_push_and_never_hold_back_its_delete() -> None:
    """A push re-reads current truth when it runs, so one queued push per ulid covers every save
    until then; a hard delete is its own job."""
    import bundesarchiv.app.tasks as tasks_mod

    sent: tuple[Job, ...] = (
        MirrorPush(ID_01A, "article"),
        MirrorPush(ID_01A, "article"),
        MirrorPush(ULID("01B"), "article"),
        MirrorDelete(ID_01A),
    )

    assert queued(lambda: list(map(tasks_mod.enqueue, sent)), mirror=True) == [
        MirrorPush(ID_01A, "article"),
        MirrorPush(ULID("01B"), "article"),
        MirrorDelete(ID_01A),
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
    jobs.mirror_reconcile(archive, InMemoryObjectStore(), PostgresPushRecord(), size=lambda: None)
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
            Archive.of(store), InMemoryObjectStore(), InMemoryPushRecord(), size=lambda: None
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
        jobs.run(MirrorPush(ID_01FOTO, "article"), _deps(store, Broken()))

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
def test_the_reconcile_queues_a_page_text_job_per_article_missing_text_and_reads_no_pdf(
    store: InMemoryObjectStore,
) -> None:
    from bundesarchiv.index.models import MediaText

    articles = ArticleRepository(store)
    for ulid in ("01HEFT", "01ZWEI"):
        refs = tuple(
            articles.add_media(ULID(ulid), name, io.BytesIO(text_pdf([name])))
            for name in ("a.pdf", "b.pdf")
        )
        articles.save(Article(ULID(ulid), "Heft", ID_FOTOS, media=refs), 0, changed_by="tester")

    enqueued: list[Job] = []
    jobs.reconcile(Archive.of(store), enqueued.append)

    assert sorted(enqueued, key=str) == [PageText(ULID("01HEFT")), PageText(ULID("01ZWEI"))]
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
        queued(lambda: tasks_mod.reconcile.func(timestamp=0), refuse=frozenset({PageText}))

    assert ArticleIndex.objects.filter(ulid="01HEFT").exists()


#: One job of each kind.
_EVERY_JOB: tuple[Job, ...] = (
    ReindexArticle(ID_01A),
    ReindexSubtree(ID_FOTOS),
    Thumbnail(ID_01A, "hash-a"),
    PageText(ID_01A),
    MirrorPush(ID_01A, "article"),
    MirrorPush(ID_FOTOS, "collection"),
    MirrorDelete(ID_01A),
)


def test_every_kind_of_job_is_sampled() -> None:
    assert {type(job) for job in _EVERY_JOB} == set(get_args(Job.__value__))


@pytest.mark.parametrize("job", _EVERY_JOB, ids=repr)
def test_a_queued_job_is_the_job_the_worker_runs(job: Job) -> None:
    import bundesarchiv.app.tasks as tasks_mod

    assert queued(lambda: tasks_mod.enqueue(job), mirror=True) == [job]


def test_each_job_is_queued_as_its_task_with_its_references_as_arguments() -> None:
    """The names and arguments Procrastinate stores: a change strands the jobs queued before a deploy."""
    import bundesarchiv.app.tasks as tasks_mod

    calls = queued_calls(lambda: list(map(tasks_mod.enqueue, _EVERY_JOB)), mirror=True)

    assert calls == [
        ("reindex_article", {"ulid": "01A"}),
        ("reindex_subtree", {"collection_ulid": "FOTOS"}),
        ("generate_thumbnail", {"ulid": "01A", "content_hash": "hash-a"}),
        ("extract_media_text", {"ulid": "01A"}),
        ("mirror_push", {"ulid": "01A", "kind": "article"}),
        ("mirror_push", {"ulid": "FOTOS", "kind": "collection"}),
        ("mirror_delete_article", {"ulid": "01A"}),
    ]


def test_a_queued_page_text_or_push_stands_in_for_the_next_and_no_other_job_does() -> None:
    """Both read current truth when they run, so the one already queued does the next one's work."""
    import bundesarchiv.app.tasks as tasks_mod

    twice = [job for job in _EVERY_JOB for _ in range(2)]
    stood_in = {PageText(ID_01A), MirrorPush(ID_01A, "article"), MirrorPush(ID_FOTOS, "collection")}

    assert queued(lambda: list(map(tasks_mod.enqueue, twice)), mirror=True) == [
        repeated for job in _EVERY_JOB for repeated in [job] * (1 if job in stood_in else 2)
    ]
