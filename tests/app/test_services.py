"""The write services (``bundesarchiv.app``): canonical CAS write, then the index sync (app law, ADR 0013/0014).

Holds the staleness gate (ADR 0014): ``rebuild()`` is forbidden inside the gate tests.
"""

import contextlib
import io
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

import pytest
from tests._queue import queued

from bundesarchiv.app.archive import Archive, IndexOver
from bundesarchiv.app.articles import (
    PageText,
    Thumbnail,
    copy_article,
    create_article,
    delete_article,
    derived_jobs,
    hard_delete_article,
    restore_article,
    save_article,
    update_article,
)
from bundesarchiv.app.collections import create_collection, save_collection
from bundesarchiv.app.result import Conflicted, CreateResult, Missing, SaveResult, Updated
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    MediaRef,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public
from bundesarchiv.index.query import SearchFilters, search
from bundesarchiv.index.refresh import InMemoryIndex, PostgresIndex, Refresh
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import StoredCollection

ID_01FOTO = ULID("01FOTO")
ID_FOTOS = ULID("FOTOS")
ID_ROOT = ULID("ROOT")

PLAIN_MEMBER = Member(())
PUBLIC = Public()


@pytest.fixture
def refreshed() -> list[Refresh]:
    return []


@pytest.fixture
def archive(refreshed: list[Refresh]) -> Archive:
    """The fixture archive over an in-memory index that records into ``refreshed``."""
    return _filled(Archive.of(InMemoryObjectStore(), partial(InMemoryIndex, refreshed=refreshed)))


@pytest.fixture
def pg_archive() -> Archive:
    """The fixture archive over the index ``Archive.of`` builds by default, Postgres."""
    return _filled(Archive.of(InMemoryObjectStore()))


def _with_lock_timeout(archive: Archive) -> Archive:
    return Archive.of(archive.store, partial(PostgresIndex, lock_timeout_ms=100))


def _failing(archive: Archive) -> Archive:
    return Archive.of(archive.store, partial(InMemoryIndex, failing=True))


def _filled(archive: Archive) -> Archive:
    """ROOT (Members) -> FOTOS (PUBLIC); one published article under FOTOS, saved through the
    repositories but NOT yet indexed (services own the indexing)."""
    collections = archive.collections
    articles = archive.articles
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
            title="Öffentliches Foto",
            collection_id=ID_FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
            date=EdtfDate("1965"),
        ),
        0,
        changed_by="tester",
    )
    return archive


def _pub_titles(viewer: object) -> set[str]:
    return {hit.title for hit in search(viewer, page_size=200).hits}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# save_article — happy path indexes synchronously
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_writes_canonical_and_indexes(pg_archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = pg_archive.articles
    stored = articles.load(ID_01FOTO)
    result = save_article(pg_archive, stored.article, stored.version, changed_by="tester")

    assert isinstance(result, SaveResult)
    assert result.index_updated is True
    assert result.version == 2  # stored at v1 in the fixture; save bumps to v2
    row = ArticleIndex.objects.get(ulid="01FOTO")
    assert row.tier == "PUBLIC"


@pytest.mark.django_db
def test_save_article_conflict_propagates_without_indexing(pg_archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex
    from bundesarchiv.persistence.errors import Conflict

    articles = pg_archive.articles
    stored = articles.load(ID_01FOTO)
    with pytest.raises(Conflict):
        save_article(pg_archive, stored.article, stored.version - 1, changed_by="tester")  # stale
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()  # no index write on failure


# ---------------------------------------------------------------------------
# update_article — the retrying load-mutate-save cycle (ADR 0013)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_article_applies_the_mutation_and_indexes(pg_archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    outcome = update_article(
        pg_archive, ID_01FOTO, lambda a: replace(a, title="Umbenannt"), changed_by="tester"
    )

    assert isinstance(outcome, Updated)
    assert outcome.article.title == "Umbenannt"
    assert outcome.version == 2  # the fixture stored it at v1
    assert outcome.index_updated is True
    assert pg_archive.articles.load(ID_01FOTO).article.title == "Umbenannt"
    assert ArticleIndex.objects.get(ulid="01FOTO").title == "Umbenannt"


def test_update_article_retries_onto_the_winner_of_a_concurrent_write(archive: Archive) -> None:
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        if calls == 1:
            stored = archive.articles.load(ID_01FOTO)
            archive.articles.save(
                replace(stored.article, creator="Konkurrenz"), stored.version, changed_by="tester"
            )
        return replace(article, title="Umbenannt")

    outcome = update_article(archive, ID_01FOTO, mutate, changed_by="tester")

    assert isinstance(outcome, Updated)
    assert calls == 2  # one loss, one retry
    assert outcome.version == 3  # v1 -> the concurrent write -> ours
    final = archive.articles.load(ID_01FOTO).article
    assert (final.title, final.creator) == ("Umbenannt", "Konkurrenz")


def test_update_article_reports_conflicted_when_every_attempt_loses(archive: Archive) -> None:
    """A mutate that loses every race gets ``Conflicted`` — never a silent no-op and never a 500.
    Nothing of ours is committed; the concurrent writer's state stands."""
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        stored = archive.articles.load(ID_01FOTO)
        archive.articles.save(
            replace(stored.article, creator=f"Konkurrenz {calls}"),
            stored.version,
            changed_by="tester",
        )
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, ID_01FOTO, mutate, retries=1, changed_by="tester")

    assert isinstance(outcome, Conflicted)
    assert calls == 2  # the first attempt plus exactly one retry
    final = archive.articles.load(ID_01FOTO).article
    assert final.title == "Öffentliches Foto"  # our mutation never landed
    assert final.creator == "Konkurrenz 2"


def test_update_article_without_retries_gives_up_on_the_first_loss(archive: Archive) -> None:
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        stored = archive.articles.load(ID_01FOTO)
        archive.articles.save(
            replace(stored.article, creator="Konkurrenz"), stored.version, changed_by="tester"
        )
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, ID_01FOTO, mutate, retries=0, changed_by="tester")

    assert isinstance(outcome, Conflicted)
    assert calls == 1
    assert archive.articles.load(ID_01FOTO).article.title == "Öffentliches Foto"


def test_update_article_reports_missing_for_an_absent_article(archive: Archive) -> None:
    outcome = update_article(
        archive, ULID("01NOSUCH"), lambda a: replace(a, title="Egal"), changed_by="tester"
    )

    assert isinstance(outcome, Missing)
    assert not [key for key in archive.store.list() if "01NOSUCH" in key]  # nothing minted


def test_update_article_reports_missing_when_the_article_vanishes_mid_retry(
    archive: Archive,
) -> None:
    """The article was there at load time but hard-deleted before the retry re-loads it — the
    caller must learn it is gone (a 404), not that it merely lost a race."""

    def mutate(article: Article) -> Article:
        # after the load, before our save -> Conflict
        archive.articles.hard_delete(ID_01FOTO, archive.articles.load(ID_01FOTO).version)
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, ID_01FOTO, mutate, changed_by="tester")

    assert isinstance(outcome, Missing)


def test_update_article_leaves_an_article_in_the_trash_alone(archive: Archive) -> None:
    """ADR 0022: restore it first."""
    stored = archive.articles.load(ID_01FOTO)
    archive.articles.mark_deleted(stored.article, stored.version, changed_by="bert")
    before = archive.articles.load(ID_01FOTO)

    outcome = update_article(
        archive, ID_01FOTO, lambda a: replace(a, title="Nie gespeichert"), changed_by="tester"
    )

    assert (outcome, archive.articles.load(ID_01FOTO)) == (Missing(), before)


# ---------------------------------------------------------------------------
# delete_article / restore_article — the Papierkorb (ADR 0022)
# ---------------------------------------------------------------------------


def _archivist_titles(*, deleted: bool) -> set[str]:
    page = search(Archivist(), filters=SearchFilters(deleted=deleted), page_size=200)
    return {hit.title for hit in page.hits}


@pytest.mark.django_db
def test_delete_and_restore_move_the_article_between_the_list_and_the_trash(
    pg_archive: Archive,
) -> None:
    stored = pg_archive.articles.load(ID_01FOTO)
    save_article(pg_archive, stored.article, stored.version, changed_by="tester")
    assert _archivist_titles(deleted=False) == {"Öffentliches Foto"}

    stored = pg_archive.articles.load(ID_01FOTO)
    deleted = delete_article(pg_archive, stored.article, stored.version, changed_by="bert")
    assert deleted.index_updated
    assert (_archivist_titles(deleted=False), _archivist_titles(deleted=True)) == (
        set(),
        {"Öffentliches Foto"},
    )

    marked = pg_archive.articles.load(ID_01FOTO).article
    restored = restore_article(pg_archive, marked, deleted.version, changed_by="anna")
    assert restored.index_updated
    assert (_archivist_titles(deleted=False), _archivist_titles(deleted=True)) == (
        {"Öffentliches Foto"},
        set(),
    )


# ---------------------------------------------------------------------------
# create_article — mints ulid, saves, indexes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_article_mints_ulid_and_indexes(pg_archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    result = create_article(
        pg_archive,
        title="Neuer Artikel",
        collection_id=ID_FOTOS,
        lifecycle=Lifecycle.PUBLISHED,
        changed_by="tester",
    )
    assert result.index_updated is True
    assert result.version == 1
    row = ArticleIndex.objects.get(ulid=result.ulid)
    assert row.title == "Neuer Artikel"
    assert row.tier == "PUBLIC"


# ---------------------------------------------------------------------------
# create_collection
# ---------------------------------------------------------------------------


def test_create_collection_mints_ulid_and_saves_top_level(archive: Archive) -> None:
    result = create_collection(archive, name="Neuer Bestand", parent_id=None, changed_by="tester")
    assert result.version == 1
    stored = archive.collections.load(result.ulid)
    assert stored.collection.name == "Neuer Bestand"
    assert stored.collection.parent_id is None
    assert stored.collection.audience is None  # inherit by default


def test_create_collection_under_parent_with_audience(archive: Archive) -> None:
    result = create_collection(
        archive,
        name="Unterbestand",
        parent_id=ID_FOTOS,
        audience=Audience(AudienceTier.MEMBERS),
        changed_by="tester",
    )
    stored = archive.collections.load(result.ulid)
    assert stored.collection.parent_id == "FOTOS"
    assert stored.collection.audience == Audience(AudienceTier.MEMBERS)


def test_create_collection_rejects_absent_parent(archive: Archive) -> None:
    # a parent that does not exist must be refused (no oracle, fail closed) — nothing created.
    from bundesarchiv.persistence.errors import NotFound

    with pytest.raises(NotFound):
        create_collection(archive, name="Waise", parent_id=ULID("NOSUCH"), changed_by="tester")
    # the collection set is unchanged (only the fixture's ROOT + FOTOS)
    ulids = {c.ulid for c in archive.collections.load_all()}
    assert ulids == {"ROOT", "FOTOS"}


# ---------------------------------------------------------------------------
# copy_article — copies metadata, clears Signatur, no media, new DRAFT
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_copy_article_copies_metadata_clears_ref_code_and_media(
    pg_archive: Archive,
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = pg_archive.articles
    # store a real blob so the source can reference it (repository refuses an unstored ref)
    ref = articles.add_media(
        ULID("01SOURCE"), "bild.jpg", io.BytesIO(b"pixels"), "image/jpeg", "Am See"
    )
    source = Article(
        ulid=ULID("01SOURCE"),
        title="Sommerfahrt 1962",
        collection_id=ID_FOTOS,
        lifecycle=Lifecycle.PUBLISHED,
        ref_code="F12/3",
        media_type="Foto",
        tags=("fahrt", "sommer"),
        physical_location="Regal 4",
        media=(ref,),
        date=EdtfDate("1962"),
        creator="K. Meier",
        custom=(("Fotograf", "Meyer"),),
        added_at=datetime(2017, 6, 26, 6, 6, 40, tzinfo=UTC),
    )
    articles.save(source, 0, changed_by="tester")

    result = copy_article(pg_archive, source, changed_by="tester")

    copy = articles.load(result.ulid).article
    assert copy.ulid != "01SOURCE"  # a fresh identity
    assert copy.lifecycle is Lifecycle.DRAFT  # a copy always starts as a draft
    assert copy.ref_code is None  # Signatur cleared (spec §7)
    assert copy.media == ()  # NO media copied (spec §7)
    assert copy.added_at is not None and copy.added_at > datetime(2017, 6, 27, tzinfo=UTC)
    # metadata carried over
    assert copy.title == "Sommerfahrt 1962"
    assert copy.collection_id == "FOTOS"
    assert copy.tags == ("fahrt", "sommer")
    assert copy.physical_location == "Regal 4"
    assert copy.date is not None and copy.date.value == "1962"
    assert copy.creator == "K. Meier"
    assert dict(copy.custom) == {"Fotograf": "Meyer"}
    # the copy is indexed too (it is a real new article)
    assert result.index_updated is True
    assert ArticleIndex.objects.filter(ulid=result.ulid).exists()


def test_copy_article_source_untouched(archive: Archive) -> None:
    articles = archive.articles
    source = Article(ulid=ULID("01SRC"), title="Original", collection_id=ID_FOTOS, ref_code="F1")
    articles.save(source, 0, changed_by="tester")
    copy_article(archive, source, changed_by="tester")
    original = articles.load(ULID("01SRC")).article
    assert original.ref_code == "F1"  # source Signatur intact
    assert original.title == "Original"


# ---------------------------------------------------------------------------
# hard_delete_article — removes canonical then drops the index row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hard_delete_article_removes_index_row(pg_archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = pg_archive.articles
    save_article(
        pg_archive,
        articles.load(ID_01FOTO).article,
        articles.load(ID_01FOTO).version,
        changed_by="tester",
    )
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    result = hard_delete_article(pg_archive, ID_01FOTO, pg_archive.articles.load(ID_01FOTO).version)
    assert result.index_updated is True
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


def test_hard_delete_article_stands_when_the_remote_delete_cannot_be_enqueued(
    archive: Archive,
) -> None:
    version = archive.articles.load(ID_01FOTO).version
    results: list[SaveResult] = []
    jobs = queued(
        lambda: results.append(hard_delete_article(archive, ID_01FOTO, version)),
        mirror=True,
        refuse=frozenset({"mirror_delete_article"}),
    )
    (result,) = results

    assert jobs == []
    assert (result.index_updated, list(archive.articles.list_ulids())) == (True, [])


# ---------------------------------------------------------------------------
# Sync-failure path — canonical write STANDS, job enqueued, index_updated=False
# ---------------------------------------------------------------------------


def test_save_article_index_failure_stands_canonical_and_enqueues(
    archive: Archive,
) -> None:
    archive = _failing(archive)
    articles = archive.articles
    stored = articles.load(ID_01FOTO)
    results: list[SaveResult] = []
    jobs = queued(
        lambda: results.append(
            save_article(archive, stored.article, stored.version, changed_by="tester")
        )
    )
    (result,) = results

    assert result.index_updated is False
    assert result.version == 2  # canonical write STOOD despite the index failure
    assert jobs == [("reindex_article", {"ulid": "01FOTO"})]  # the retry, and no push: no mirror
    # canonical truth is durable at the new version:
    assert archive.articles.load(ID_01FOTO).version == 2


def test_save_article_swallows_enqueue_failure_after_index_failure(
    archive: Archive,
) -> None:
    archive = _failing(archive)
    articles = archive.articles
    stored = articles.load(ID_01FOTO)
    results: list[SaveResult] = []
    queued(
        lambda: results.append(
            save_article(archive, stored.article, stored.version, changed_by="tester")
        ),
        refuse=frozenset({"reindex_article"}),
    )
    (result,) = results

    assert result.index_updated is False
    assert result.version == 2  # canonical write STOOD despite both failures
    assert archive.articles.load(ID_01FOTO).version == 2


def test_save_collection_swallows_enqueue_failure_after_index_failure(
    archive: Archive,
) -> None:
    archive = _failing(archive)
    stored = archive.collections.load(ID_FOTOS)
    results: list[SaveResult] = []
    queued(
        lambda: results.append(
            save_collection(
                archive, _narrowed(stored.collection), stored.version, changed_by="tester"
            )
        ),
        refuse=frozenset({"reindex_subtree"}),
    )
    (result,) = results

    assert (result.version, result.index_updated) == (2, False)
    assert archive.collections.load(ID_FOTOS).version == 2


def test_a_write_refreshes_the_index_once_the_store_holds_it(
    archive: Archive, refreshed: list[Refresh]
) -> None:
    """A refresh re-reads the store, so it runs after the canonical write (ADR 0014)."""
    stored = archive.articles.load(ID_01FOTO)
    saved = save_article(archive, stored.article, stored.version, changed_by="t")
    marked = delete_article(archive, stored.article, saved.version, changed_by="t")
    hard_delete_article(archive, ID_01FOTO, marked.version)
    fotos = archive.collections.load(ID_FOTOS)
    save_collection(archive, _narrowed(fotos.collection), fotos.version, changed_by="t")

    assert refreshed == [
        ("article", "01FOTO", 2),
        ("article", "01FOTO", 3),
        ("article", "01FOTO", None),
        ("subtree", "FOTOS", 2),
    ]


@pytest.mark.parametrize(
    "index",
    [
        pytest.param(InMemoryIndex, id="in-memory"),
        pytest.param(PostgresIndex, id="postgres", marks=pytest.mark.django_db),
    ],
)
def test_refreshing_what_the_store_does_not_hold_is_not_an_error(index: IndexOver) -> None:
    over_empty = index(InMemoryObjectStore())
    over_empty.refresh_article(ULID("01NEVER"))
    over_empty.refresh_subtree(ULID("NOSUCH"))


@pytest.mark.django_db(transaction=True)
def test_save_article_gives_up_on_a_held_index_lock_and_enqueues(pg_archive: Archive) -> None:
    """A save whose index update cannot get the index-writer lock within the sync bound (a rebuild
    holds it) returns index_updated=False, writes no row and queues the retry instead of waiting
    the holder out."""
    from bundesarchiv.index.models import ArticleIndex

    archive = _with_lock_timeout(pg_archive)
    stored = archive.articles.load(ID_01FOTO)
    with _index_lock_held():
        started = time.monotonic()
        results: list[SaveResult] = []
        jobs = queued(
            lambda: results.append(
                save_article(archive, stored.article, stored.version, changed_by="tester")
            )
        )
        elapsed = time.monotonic() - started
    (result,) = results

    assert result.index_updated is False
    assert jobs == [("reindex_article", {"ulid": "01FOTO"})]
    assert elapsed < 2
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — article unpublish (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_unpublishing_article_via_service_hides_it_next_search(
    pg_archive: Archive,
) -> None:
    articles = pg_archive.articles
    save_article(
        pg_archive,
        articles.load(ID_01FOTO).article,
        articles.load(ID_01FOTO).version,
        changed_by="tester",
    )
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)

    stored = articles.load(ID_01FOTO)
    unpublished = Article(
        ulid=ID_01FOTO,
        title="Öffentliches Foto",
        collection_id=ID_FOTOS,
        lifecycle=Lifecycle.DRAFT,  # unpublished -> archivist-only
        date=EdtfDate("1965"),
    )
    save_article(pg_archive, unpublished, stored.version, changed_by="tester")

    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # gone for Public
    assert "Öffentliches Foto" not in _pub_titles(PLAIN_MEMBER)  # gone for Members too


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — collection audience narrowing (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_narrowing_collection_audience_via_service_hides_descendants(
    pg_archive: Archive,
) -> None:
    articles = pg_archive.articles
    save_article(
        pg_archive,
        articles.load(ID_01FOTO).article,
        articles.load(ID_01FOTO).version,
        changed_by="tester",
    )
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)  # visible to Public via FOTOS=PUBLIC

    collections = pg_archive.collections
    stored = collections.load(ID_FOTOS)
    result = save_collection(
        pg_archive,
        Collection(
            ulid=ID_FOTOS,
            name="Fotos",
            parent_id=ID_ROOT,
            audience=Audience(AudienceTier.MEMBERS),  # narrow PUBLIC -> MEMBERS
        ),
        stored.version,
        changed_by="tester",
    )

    assert result.index_updated is True
    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # descendant hidden from Public
    assert "Öffentliches Foto" in _pub_titles(PLAIN_MEMBER)  # still visible to Members


# ---------------------------------------------------------------------------
# Derived-file jobs — save and create queue a job per file to render and one to read
# ---------------------------------------------------------------------------


def test_derived_jobs_render_image_and_pdf_files_and_read_pdfs_once() -> None:
    """A file renders by its media type, or by its extension when the type is absent; any PDF
    gives the one page-text job."""
    article = Article(
        ulid=ID_01FOTO,
        title="Mixed media",
        collection_id=ID_FOTOS,
        media=(
            MediaRef("a.jpg", "hash-typed-image", media_type="image/jpeg"),
            MediaRef("b.png", "hash-untyped-image", media_type=None),
            MediaRef("c.pdf", "hash-doc", media_type="application/pdf"),
            MediaRef("d.PDF", "hash-untyped-doc", media_type=None),
            MediaRef("e.txt", "hash-text", media_type="text/plain"),
            MediaRef("f.bin", "hash-unknown", media_type=None),
        ),
    )

    assert derived_jobs(article) == (
        Thumbnail(ID_01FOTO, "hash-typed-image"),
        Thumbnail(ID_01FOTO, "hash-untyped-image"),
        Thumbnail(ID_01FOTO, "hash-doc"),
        Thumbnail(ID_01FOTO, "hash-untyped-doc"),
        PageText(ID_01FOTO),
    )
    assert derived_jobs(replace(article, media=article.media[:2])) == (
        Thumbnail(ID_01FOTO, "hash-typed-image"),
        Thumbnail(ID_01FOTO, "hash-untyped-image"),
    )


def _save_scan_and_pdf(archive: Archive) -> None:
    articles = archive.articles
    image = articles.add_media(
        ID_01FOTO, "scan.jpg", io.BytesIO(b"\xff\xd8\xff-fake"), media_type="image/jpeg"
    )
    doc = articles.add_media(ID_01FOTO, "notes.pdf", io.BytesIO(b"%PDF-1.7"))
    stored = articles.load(ID_01FOTO)
    save_article(
        archive, replace(stored.article, media=(image, doc)), stored.version, changed_by="tester"
    )


def test_a_save_queues_the_jobs_its_files_derive(archive: Archive) -> None:
    jobs = queued(lambda: _save_scan_and_pdf(archive))

    image, doc = archive.articles.load(ID_01FOTO).article.media
    assert jobs == [
        ("generate_thumbnail", {"ulid": "01FOTO", "content_hash": image.content_hash}),
        ("generate_thumbnail", {"ulid": "01FOTO", "content_hash": doc.content_hash}),
        ("extract_media_text", {"ulid": "01FOTO"}),
    ]


def test_a_failed_thumbnail_enqueue_neither_breaks_the_save_nor_skips_the_page_text(
    archive: Archive,
) -> None:
    jobs = queued(lambda: _save_scan_and_pdf(archive), refuse=frozenset({"generate_thumbnail"}))

    saved = archive.articles.load(ID_01FOTO).article
    assert [ref.filename for ref in saved.media] == ["scan.jpg", "notes.pdf"]
    assert jobs == [("extract_media_text", {"ulid": "01FOTO"})]


# ---------------------------------------------------------------------------
# The push enqueue (ADR 0020) — one reference job per saved Article or Collection
# ---------------------------------------------------------------------------


def test_save_article_enqueues_one_push_of_the_article(archive: Archive) -> None:
    stored = archive.articles.load(ID_01FOTO)
    jobs = queued(
        lambda: save_article(archive, stored.article, stored.version, changed_by="tester"),
        mirror=True,
    )

    assert jobs == [("mirror_push", {"ulid": "01FOTO"})]


def test_a_write_enqueues_nothing_without_a_mirror(archive: Archive) -> None:
    stored = archive.articles.load(ID_01FOTO)
    jobs = queued(
        lambda: save_article(archive, stored.article, stored.version, changed_by="tester")
    )

    assert jobs == []


def test_delete_article_enqueues_one_push_of_the_mark(archive: Archive) -> None:
    stored = archive.articles.load(ID_01FOTO)
    jobs = queued(
        lambda: delete_article(archive, stored.article, stored.version, changed_by="tester"),
        mirror=True,
    )

    assert jobs == [("mirror_push", {"ulid": "01FOTO"})]


def test_hard_delete_article_enqueues_the_delete_and_no_push(archive: Archive) -> None:
    version = archive.articles.load(ID_01FOTO).version
    jobs = queued(lambda: hard_delete_article(archive, ID_01FOTO, version), mirror=True)

    assert jobs == [("mirror_delete_article", {"ulid": "01FOTO"})]


def test_create_article_enqueues_the_push_of_the_new_article(archive: Archive) -> None:
    created: list[CreateResult] = []
    jobs = queued(
        lambda: created.append(
            create_article(archive, title="Neu", collection_id=ID_FOTOS, changed_by="tester")
        ),
        mirror=True,
    )

    assert jobs == [("mirror_push", {"ulid": created[0].ulid})]


def test_save_collection_enqueues_one_push_of_the_collection(archive: Archive) -> None:
    stored = archive.collections.load(ID_FOTOS)
    jobs = queued(
        lambda: save_collection(archive, stored.collection, stored.version, changed_by="tester"),
        mirror=True,
    )

    assert jobs == [("mirror_push", {"ulid": "FOTOS"})]


def test_save_article_mirror_enqueue_failure_does_not_break_save(archive: Archive) -> None:
    """The reconcile heals a lost push (ADR 0020)."""
    articles = archive.articles
    stored = articles.load(ID_01FOTO)
    results: list[SaveResult] = []
    queued(
        lambda: results.append(
            save_article(archive, stored.article, stored.version, changed_by="tester")
        ),
        mirror=True,
        refuse=frozenset({"mirror_push"}),
    )
    (result,) = results

    assert result.version == 2  # save succeeded despite the mirror-enqueue failure
    assert archive.articles.load(ID_01FOTO).version == 2


@contextlib.contextmanager
def _index_lock_held() -> Generator[None]:
    """Hold the index-writer lock from another connection for the duration of the block."""
    from django.db import connection, transaction

    from bundesarchiv.index.indexer import _take_writer_lock

    held, release = threading.Event(), threading.Event()

    def hold_lock() -> None:
        try:
            with transaction.atomic():
                _take_writer_lock()
                held.set()
                release.wait(timeout=5)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_lock)
        assert held.wait(timeout=5)
        try:
            yield
        finally:
            release.set()
            holder.result()


def _narrowed(collection: Collection) -> Collection:
    return replace(collection, audience=Audience(AudienceTier.MEMBERS))


@pytest.mark.django_db(transaction=True)
def test_save_collection_gives_up_on_a_held_index_lock_and_enqueues(pg_archive: Archive) -> None:
    """The Bestand save path has the same bound as the Article save path."""
    archive = _with_lock_timeout(pg_archive)
    stored = archive.collections.load(ID_FOTOS)
    with _index_lock_held():
        started = time.monotonic()
        results: list[SaveResult] = []
        jobs = queued(
            lambda: results.append(
                save_collection(
                    archive, _narrowed(stored.collection), stored.version, changed_by="tester"
                )
            )
        )
        elapsed = time.monotonic() - started
    (result,) = results

    assert result.index_updated is False
    assert jobs == [("reindex_subtree", {"collection_ulid": "FOTOS"})]
    assert elapsed < 2


@pytest.mark.django_db(transaction=True)
def test_a_rename_and_a_new_collection_leave_the_index_as_it_is(pg_archive: Archive) -> None:
    """The index holds no Bestand name and a new Bestand holds no Articles, so neither waits on the
    index lock nor queues a reindex, and the renamed Bestand still finds its Article."""
    stored_article = pg_archive.articles.load(ID_01FOTO)
    save_article(pg_archive, stored_article.article, stored_article.version, changed_by="tester")
    archive = _with_lock_timeout(pg_archive)

    stored = archive.collections.load(ID_FOTOS)
    with _index_lock_held():
        results: list[SaveResult | CreateResult] = []
        jobs = queued(
            lambda: results.extend(
                (
                    save_collection(
                        archive,
                        replace(stored.collection, name="Lichtbilder"),
                        stored.version,
                        changed_by="t",
                    ),
                    create_collection(archive, name="Neu", parent_id=ID_FOTOS, changed_by="t"),
                )
            )
        )

    assert ([result.index_updated for result in results], jobs) == ([True, True], [])
    for collection_ulid in ("FOTOS", "ROOT"):
        hits = search(PUBLIC, filters=SearchFilters(collection=collection_ulid)).hits
        assert [hit.ulid for hit in hits] == ["01FOTO"], collection_ulid


@pytest.mark.django_db
def test_gate_a_rename_at_a_version_it_did_not_read_still_reindexes(
    pg_archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rename whose ``expected_version`` is ahead of the version the service read wins the CAS
    against a concurrent widening edit that lands in between, and writes the older, narrower
    audience back. Its reindex must run, or the index keeps the widened audience."""
    save_article(pg_archive, pg_archive.articles.load(ID_01FOTO).article, 1, changed_by="t")
    fotos = pg_archive.collections.load(ID_FOTOS)
    save_collection(pg_archive, _narrowed(fotos.collection), fotos.version, changed_by="t")
    narrow = pg_archive.collections.load(ID_FOTOS)
    load = pg_archive.collections.load

    def load_then_widen(ulid: str) -> StoredCollection:
        stored = load(ULID(ulid))
        monkeypatch.setattr(pg_archive.collections, "load", load)
        save_collection(pg_archive, fotos.collection, stored.version, changed_by="concurrent")
        return stored

    monkeypatch.setattr(pg_archive.collections, "load", load_then_widen)
    rename = replace(narrow.collection, name="Lichtbilder")
    save_collection(pg_archive, rename, narrow.version + 1, changed_by="t")

    assert pg_archive.collections.load(ID_FOTOS).collection == rename
    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)


@pytest.mark.django_db
def test_gate_moving_a_collection_under_a_narrower_parent_hides_its_articles(
    pg_archive: Archive,
) -> None:
    """A parent edit moves the effective audience of an inheriting subtree, like an audience edit."""
    pg_archive.collections.save(
        Collection(ulid=ULID("KIND"), name="Kind", parent_id=ID_FOTOS), 0, changed_by="t"
    )
    article = Article(
        ulid=ULID("01KIND"),
        title="Geerbt",
        collection_id=ULID("KIND"),
        lifecycle=Lifecycle.PUBLISHED,
    )
    pg_archive.articles.save(article, 0, changed_by="t")
    save_article(pg_archive, article, 1, changed_by="t")
    assert "Geerbt" in _pub_titles(PUBLIC)  # inherits PUBLIC from FOTOS

    stored = pg_archive.collections.load(ULID("KIND"))
    save_collection(
        pg_archive,
        replace(stored.collection, parent_id=ID_ROOT),
        stored.version,
        changed_by="t",
    )

    assert "Geerbt" not in _pub_titles(PUBLIC)  # now inherits the root default, Members
    assert "Geerbt" in _pub_titles(PLAIN_MEMBER)
