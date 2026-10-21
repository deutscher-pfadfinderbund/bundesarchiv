"""The incremental indexer, ``index_article`` and ``index_subtree`` (ADR 0014)."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Any

import pytest
from tests._articles import make_article
from tests._readmes import UNREADABLE_README

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.index import indexer
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import Busy
from bundesarchiv.persistence.repository import ArticleRepository

ID_01FOTO = ULID("01FOTO")
ID_01ROOT = ULID("01ROOT")
ID_FOTOS = ULID("FOTOS")
ID_ROOT = ULID("ROOT")


def _article(collection_id: str, ulid: str, **overrides: Any) -> Article:
    return replace(make_article(ulid, collection_id=collection_id, title="Ein Titel"), **overrides)


@pytest.fixture
def store() -> InMemoryObjectStore:
    """ROOT (MEMBERS default) -> FOTOS (PUBLIC) -> AKTEN (inherits); one published article per
    level, nothing indexed yet."""
    return _seed(InMemoryObjectStore())


def _seed[S: InMemoryObjectStore](store: S) -> S:
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
    collections.save(
        Collection(ulid=ULID("AKTEN"), name="Akten", parent_id=ID_FOTOS),
        0,
        changed_by="tester",
    )

    articles.save(_article("ROOT", "01ROOT", title="Wurzelartikel"), 0, changed_by="tester")
    articles.save(
        _article("FOTOS", "01FOTO", title="Foto", date=EdtfDate("1965")), 0, changed_by="tester"
    )
    articles.save(_article("AKTEN", "01AKTE", title="Akte"), 0, changed_by="tester")
    return store


# ---------------------------------------------------------------------------
# index_article — new / changed / deleted / broken-chain
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_index_article_inserts_a_new_row(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, ID_01FOTO)
    row = ArticleIndex.objects.get(ulid="01FOTO")
    assert row.tier == "PUBLIC"  # inherits PUBLIC from FOTOS
    assert row.archivist_only is False
    assert list(row.collection_ancestors) == ["FOTOS", "ROOT"]


@pytest.mark.django_db
def test_index_article_updates_a_changed_row(store: InMemoryObjectStore) -> None:
    """Re-reads canonical: an article whose audience narrowed reindexes to the new scope."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, ID_01ROOT)
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"

    articles = ArticleRepository(store)
    stored = articles.load(ID_01ROOT)
    articles.save(
        Article(
            ulid=ID_01ROOT,
            title="Wurzelartikel",
            collection_id=ID_ROOT,
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        stored.version,
        changed_by="tester",
    )
    indexer.index_article(store, ID_01ROOT)

    row = ArticleIndex.objects.get(ulid="01ROOT")
    assert row.tier == "GROUPS"
    assert list(row.groups) == ["vorstand"]
    assert ArticleIndex.objects.filter(ulid="01ROOT").count() == 1  # upsert, not duplicate


@pytest.mark.django_db
def test_index_article_deletes_row_when_article_gone(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, ID_01FOTO)
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    repo = ArticleRepository(store)
    repo.hard_delete(ID_01FOTO, repo.load(ID_01FOTO).version)
    indexer.index_article(store, ID_01FOTO)
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


@pytest.mark.django_db
def test_index_article_delete_of_missing_row_is_a_noop(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, ULID("01NEVER"))  # not in canonical, not in index
    assert not ArticleIndex.objects.filter(ulid="01NEVER").exists()


@pytest.mark.django_db
def test_index_article_broken_chain_writes_fail_closed_row(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    ArticleRepository(store).save(
        _article("GHOST", "01BAD", title="Verwaist"), 0, changed_by="tester"
    )
    indexer.index_article(store, ULID("01BAD"))

    row = ArticleIndex.objects.get(ulid="01BAD")
    assert row.archivist_only is True
    assert row.tier is None
    assert list(row.groups) == []
    assert row.title == "Verwaist"  # still findable by an Archivist
    assert list(row.collection_ancestors) == []


# ---------------------------------------------------------------------------
# index_subtree — descendants re-scoped, non-descendants untouched
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_index_subtree_reindexes_descendants_only(store: InMemoryObjectStore) -> None:
    """ROOT's article, outside the subtree, keeps its old indexed title although its canonical
    title changed."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
    assert ArticleIndex.objects.get(ulid="01AKTE").tier == "PUBLIC"  # inherits FOTOS
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"

    collections = CollectionRepository(store)
    stored = collections.load(ID_FOTOS)
    collections.save(
        Collection(
            ulid=ID_FOTOS,
            name="Fotos",
            parent_id=ID_ROOT,
            audience=Audience(AudienceTier.MEMBERS),  # narrowed PUBLIC -> MEMBERS
        ),
        stored.version,
        changed_by="tester",
    )

    articles = ArticleRepository(store)
    root_article = articles.load(ID_01ROOT)
    articles.save(
        _article("ROOT", "01ROOT", title="Neuer Titel"), root_article.version, changed_by="tester"
    )

    indexer.index_subtree(store, ID_FOTOS)

    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "MEMBERS"
    assert ArticleIndex.objects.get(ulid="01AKTE").tier == "MEMBERS"
    assert ArticleIndex.objects.get(ulid="01ROOT").title == "Wurzelartikel"


@pytest.mark.django_db
def test_index_subtree_on_root_reindexes_whole_tree(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_subtree(store, ID_ROOT)
    assert ArticleIndex.objects.count() == 3


# ---------------------------------------------------------------------------
# An unreadable README (owner 2026-10-01): archivist-only, reported, never an abort
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("data", UNREADABLE_README)
def test_rebuild_indexes_an_unreadable_article_archivist_only_and_reports_it(
    store: InMemoryObjectStore, data: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    store.write_atomic(ARTICLES.readme_key(ID_01FOTO), data)
    report = indexer.rebuild(store)
    assert report.indexed == 3
    assert report.unreadable_articles == ("01FOTO",)
    assert "01FOTO" in caplog.text
    assert ArticleIndex.objects.get(ulid="01FOTO").archivist_only is True
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"


@pytest.mark.django_db
@pytest.mark.parametrize("data", UNREADABLE_README)
def test_rebuild_treats_an_unreadable_collection_as_absent_and_reports_it(
    store: InMemoryObjectStore, data: bytes
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    store.write_atomic(COLLECTIONS.readme_key(ID_FOTOS), data)
    report = indexer.rebuild(store)
    assert report.unreadable_collections == ("FOTOS",)
    assert set(report.failed_closed) == {"01FOTO", "01AKTE"}
    assert ArticleIndex.objects.get(ulid="01AKTE").archivist_only is True
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"


@pytest.mark.django_db
@pytest.mark.parametrize("data", UNREADABLE_README)
def test_index_article_narrows_an_unreadable_article_to_archivist_only(
    store: InMemoryObjectStore, data: bytes
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    store.write_atomic(ARTICLES.readme_key(ID_01FOTO), data)
    indexer.index_article(store, ID_01FOTO)
    assert ArticleIndex.objects.get(ulid="01FOTO").archivist_only is True


@pytest.mark.django_db
@pytest.mark.parametrize("data", UNREADABLE_README)
def test_index_article_fails_closed_under_an_unreadable_collection(
    store: InMemoryObjectStore, data: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    """A save logs nothing about it: only ``rebuild`` reports an unreadable README."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    store.write_atomic(COLLECTIONS.readme_key(ID_FOTOS), data)
    caplog.clear()
    indexer.index_article(store, ULID("01AKTE"))
    assert ArticleIndex.objects.get(ulid="01AKTE").archivist_only is True
    assert caplog.text == ""


@pytest.mark.django_db
@pytest.mark.parametrize("data", UNREADABLE_README)
def test_index_subtree_goes_on_past_unreadable_readmes(
    store: InMemoryObjectStore, data: bytes
) -> None:
    """Only the subtree and its direct orphans are touched; an unreadable Article is left to
    ``rebuild``."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    store.write_atomic(COLLECTIONS.readme_key(ULID("AKTEN")), data)
    store.write_atomic(ARTICLES.readme_key(ID_01ROOT), data)
    indexer.index_subtree(store, ID_FOTOS)
    assert ArticleIndex.objects.get(ulid="01AKTE").tier == "PUBLIC"
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"
    indexer.index_subtree(store, ULID("AKTEN"))
    assert ArticleIndex.objects.get(ulid="01AKTE").archivist_only is True


class _BusyStore(InMemoryObjectStore):
    """Refuses to read one key under contention, as a backend may."""

    busy: str = ""

    def read(self, key: str) -> bytes:
        if key == self.busy:
            raise Busy(key)
        return super().read(key)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("busy", "write"),
    [
        pytest.param(
            ARTICLES.readme_key(ID_01FOTO),
            lambda s: indexer.index_article(s, ID_01FOTO),
            id="article",
        ),
        pytest.param(COLLECTIONS.readme_key(ID_FOTOS), indexer.rebuild, id="collection"),
    ],
)
def test_a_busy_store_is_no_unreadable_readme(
    busy: str, write: Callable[[InMemoryObjectStore], object]
) -> None:
    """``Busy`` is retryable: it propagates, and the row stays as it was."""
    from bundesarchiv.index.models import ArticleIndex

    store = _seed(_BusyStore())
    indexer.rebuild(store)
    store.busy = busy
    with pytest.raises(Busy):
        write(store)
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"


# ---------------------------------------------------------------------------
# Advisory-lock serialization — an index writer blocks behind a held index-writer lock
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_advisory_lock_serializes_concurrent_index_writers(
    store: InMemoryObjectStore,
) -> None:
    from django.db import connection, transaction

    from bundesarchiv.index.indexer import _take_writer_lock
    from bundesarchiv.index.models import ArticleIndex

    finished = threading.Event()

    def background_index() -> None:
        indexer.index_article(store, ID_01FOTO)
        connection.close()
        finished.set()

    with transaction.atomic():
        _take_writer_lock()  # hold the xact-scoped lock for the whole block
        worker = threading.Thread(target=background_index)
        worker.start()
        assert not finished.wait(timeout=1.0), "index writer did not serialize behind the lock"
    # Our transaction committed here -> the xact lock released -> the background write can proceed.
    assert finished.wait(timeout=5.0), "index writer did not proceed after the lock released"
    worker.join()

    assert ArticleIndex.objects.filter(ulid="01FOTO").count() == 1
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"


# ---------------------------------------------------------------------------
# Lock, then read: a writer that read before a narrowing cannot overwrite it
# ---------------------------------------------------------------------------


class _PausingStore(InMemoryObjectStore):
    """Once ``pause_on`` is set, the first read of that key returns the bytes it read only after
    ``release`` is set — a writer frozen between reading a file and writing its row."""

    def __init__(self) -> None:
        super().__init__()
        self.pause_on: str | None = None
        self.paused = threading.Event()
        self.release = threading.Event()

    def read(self, key: str) -> bytes:
        data = super().read(key)
        if key == self.pause_on and not self.paused.is_set():
            self.paused.set()
            self.release.wait(timeout=10)
        return data


def _in_thread(fn: Callable[..., object], *args: object) -> None:
    from django.db import connection

    try:
        fn(*args)
    finally:
        connection.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "writer",
    [
        pytest.param(indexer.rebuild, id="rebuild"),
        pytest.param(lambda s: indexer.index_subtree(s, ID_FOTOS), id="index_subtree"),
        pytest.param(lambda s: indexer.index_article(s, ID_01FOTO), id="index_article"),
    ],
)
def test_a_writer_mid_read_cannot_overwrite_a_later_narrowing(
    writer: Callable[[InMemoryObjectStore], object],
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    store = _seed(_PausingStore())
    store.pause_on = ARTICLES.readme_key(ID_01FOTO)
    articles = ArticleRepository(store)
    narrowed = _article(
        "FOTOS",
        "01FOTO",
        title="Foto",
        date=EdtfDate("1965"),
        audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        wide = pool.submit(_in_thread, writer, store)
        assert store.paused.wait(timeout=5)
        articles.save(narrowed, articles.load(ID_01FOTO).version, changed_by="tester")
        narrow = pool.submit(_in_thread, indexer.index_article, store, "01FOTO")
        wait([narrow], timeout=1.0)  # with the lock taken first, this waits on the paused writer
        store.release.set()
        wide.result()
        narrow.result()

    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "GROUPS"
