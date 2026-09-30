"""Task 4.2 — the application-service layer (``bundesarchiv.app``): the imperative shell the
Part 4.5+ views call. Each service is a thin, explicit two-step: the canonical repo write (CAS
per ADR 0013), THEN the synchronous index update (ADR 0014). An index failure never fails the
canonical write — it enqueues a reference job and returns a ``SaveResult`` carrying
``index_updated=False`` so the UI can show the ADR-mandated specific warning.

Includes THE ADVERSARIAL STALENESS GATE (ADR 0014 §gate): a narrowing edit made through the
PRODUCTION service entry point must be reflected in the very next ``search()`` — ``rebuild()`` is
FORBIDDEN inside the gate tests.
"""

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.articles import (
    copy_article,
    create_article,
    hard_delete_article,
    save_article,
    update_article,
)
from bundesarchiv.app.collections import create_collection, save_collection
from bundesarchiv.app.result import Conflicted, Missing, SaveResult, Updated
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Member, Public
from bundesarchiv.index.query import search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore

PLAIN_MEMBER = Member(())
PUBLIC = Public()


@pytest.fixture
def archive() -> Archive:
    """ROOT (Members) -> FOTOS (PUBLIC); one published article under FOTOS, saved through the
    repositories but NOT yet indexed (services own the indexing)."""
    archive = Archive.of(InMemoryObjectStore())
    collections = archive.collections
    articles = archive.articles
    collections.save(Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0, changed_by="tester")
    collections.save(
        Collection(
            ulid="FOTOS", name="Fotos", parent_id="ROOT", audience=Audience(AudienceTier.PUBLIC)
        ),
        0,
        changed_by="tester",
    )
    articles.save(
        Article(
            ulid="01FOTO",
            title="Öffentliches Foto",
            collection_id="FOTOS",
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
def test_save_article_writes_canonical_and_indexes(archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = archive.articles
    stored = articles.load("01FOTO")
    result = save_article(archive, stored.article, stored.version, changed_by="tester")

    assert isinstance(result, SaveResult)
    assert result.index_updated is True
    assert result.version == 2  # stored at v1 in the fixture; save bumps to v2
    row = ArticleIndex.objects.get(ulid="01FOTO")
    assert row.tier == "PUBLIC"


@pytest.mark.django_db
def test_save_article_conflict_propagates_without_indexing(archive: Archive) -> None:
    """A stale expected_version raises Conflict from the repo (ADR 0013) — nothing is indexed."""
    from bundesarchiv.index.models import ArticleIndex
    from bundesarchiv.persistence.errors import Conflict

    articles = archive.articles
    stored = articles.load("01FOTO")
    with pytest.raises(Conflict):
        save_article(archive, stored.article, stored.version - 1, changed_by="tester")  # stale
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()  # no index write on failure


# ---------------------------------------------------------------------------
# update_article — the retrying load-mutate-save cycle (ADR 0013)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_article_applies_the_mutation_and_indexes(archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    outcome = update_article(
        archive, "01FOTO", lambda a: replace(a, title="Umbenannt"), changed_by="tester"
    )

    assert isinstance(outcome, Updated)
    assert outcome.article.title == "Umbenannt"
    assert outcome.version == 2  # the fixture stored it at v1
    assert outcome.index_updated is True
    assert archive.articles.load("01FOTO").article.title == "Umbenannt"
    assert ArticleIndex.objects.get(ulid="01FOTO").title == "Umbenannt"


@pytest.mark.django_db
def test_update_article_retries_onto_the_winner_of_a_concurrent_write(archive: Archive) -> None:
    """A real race, no monkeypatching: the mutate closure commits a concurrent write on its first
    call, so the first save loses. The retry must re-apply the mutation to the WINNER's article —
    the concurrent creator survives alongside our title."""
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        if calls == 1:
            stored = archive.articles.load("01FOTO")
            archive.articles.save(
                replace(stored.article, creator="Konkurrenz"), stored.version, changed_by="tester"
            )
        return replace(article, title="Umbenannt")

    outcome = update_article(archive, "01FOTO", mutate, changed_by="tester")

    assert isinstance(outcome, Updated)
    assert calls == 2  # one loss, one retry
    assert outcome.version == 3  # v1 -> the concurrent write -> ours
    final = archive.articles.load("01FOTO").article
    assert (final.title, final.creator) == ("Umbenannt", "Konkurrenz")


@pytest.mark.django_db
def test_update_article_reports_conflicted_when_every_attempt_loses(archive: Archive) -> None:
    """A mutate that loses every race gets ``Conflicted`` — never a silent no-op and never a 500.
    Nothing of ours is committed; the concurrent writer's state stands."""
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        stored = archive.articles.load("01FOTO")
        archive.articles.save(
            replace(stored.article, creator=f"Konkurrenz {calls}"),
            stored.version,
            changed_by="tester",
        )
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, "01FOTO", mutate, retries=1, changed_by="tester")

    assert isinstance(outcome, Conflicted)
    assert calls == 2  # the first attempt plus exactly one retry
    final = archive.articles.load("01FOTO").article
    assert final.title == "Öffentliches Foto"  # our mutation never landed
    assert final.creator == "Konkurrenz 2"


@pytest.mark.django_db
def test_update_article_without_retries_gives_up_on_the_first_loss(archive: Archive) -> None:
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        stored = archive.articles.load("01FOTO")
        archive.articles.save(
            replace(stored.article, creator="Konkurrenz"), stored.version, changed_by="tester"
        )
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, "01FOTO", mutate, retries=0, changed_by="tester")

    assert isinstance(outcome, Conflicted)
    assert calls == 1
    assert archive.articles.load("01FOTO").article.title == "Öffentliches Foto"


@pytest.mark.django_db
def test_update_article_reports_missing_for_an_absent_article(archive: Archive) -> None:
    outcome = update_article(
        archive, "01NOSUCH", lambda a: replace(a, title="Egal"), changed_by="tester"
    )

    assert isinstance(outcome, Missing)
    assert not [key for key in archive.store.list() if "01NOSUCH" in key]  # nothing minted


@pytest.mark.django_db
def test_update_article_reports_missing_when_the_article_vanishes_mid_retry(
    archive: Archive,
) -> None:
    """The article was there at load time but hard-deleted before the retry re-loads it — the
    caller must learn it is gone (a 404), not that it merely lost a race."""

    def mutate(article: Article) -> Article:
        # after the load, before our save -> Conflict
        archive.articles.hard_delete("01FOTO", archive.articles.load("01FOTO").version)
        return replace(article, title="Nie gespeichert")

    outcome = update_article(archive, "01FOTO", mutate, changed_by="tester")

    assert isinstance(outcome, Missing)


# ---------------------------------------------------------------------------
# create_article — mints ulid, saves, indexes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_article_mints_ulid_and_indexes(archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    result = create_article(
        archive,
        title="Neuer Artikel",
        collection_id="FOTOS",
        lifecycle=Lifecycle.PUBLISHED,
        changed_by="tester",
    )
    assert result.index_updated is True
    assert result.version == 1
    row = ArticleIndex.objects.get(ulid=result.ulid)
    assert row.title == "Neuer Artikel"
    assert row.tier == "PUBLIC"


# ---------------------------------------------------------------------------
# create_collection — mints ulid, saves at v1, validates parent (4.8)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_collection_mints_ulid_and_saves_top_level(archive: Archive) -> None:
    result = create_collection(archive, name="Neuer Bestand", parent_id=None, changed_by="tester")
    assert result.version == 1
    stored = archive.collections.load(result.ulid)
    assert stored.collection.name == "Neuer Bestand"
    assert stored.collection.parent_id is None
    assert stored.collection.audience is None  # inherit by default


@pytest.mark.django_db
def test_create_collection_under_parent_with_audience(archive: Archive) -> None:
    result = create_collection(
        archive,
        name="Unterbestand",
        parent_id="FOTOS",
        audience=Audience(AudienceTier.MEMBERS),
        changed_by="tester",
    )
    stored = archive.collections.load(result.ulid)
    assert stored.collection.parent_id == "FOTOS"
    assert stored.collection.audience == Audience(AudienceTier.MEMBERS)


@pytest.mark.django_db
def test_create_collection_rejects_absent_parent(archive: Archive) -> None:
    # a parent that does not exist must be refused (no oracle, fail closed) — nothing created.
    from bundesarchiv.persistence.errors import NotFound

    with pytest.raises(NotFound):
        create_collection(archive, name="Waise", parent_id="NOSUCH", changed_by="tester")
    # the collection set is unchanged (only the fixture's ROOT + FOTOS)
    ulids = {c.ulid for c in archive.collections.load_all()}
    assert ulids == {"ROOT", "FOTOS"}


# ---------------------------------------------------------------------------
# copy_article — copies metadata, clears Signatur, no media, new DRAFT
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_copy_article_copies_metadata_clears_signatur_and_media(
    archive: Archive,
) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = archive.articles
    # store a real blob so the source can reference it (repository refuses an unstored ref)
    ref = articles.add_media("01SOURCE", "bild.jpg", io.BytesIO(b"pixels"), "image/jpeg", "Am See")
    # a rich source: published, with a Signatur, media, tags, custom, date, an audience
    source = Article(
        ulid="01SOURCE",
        title="Sommerfahrt 1962",
        collection_id="FOTOS",
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

    result = copy_article(archive, "01SOURCE", changed_by="tester")

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


@pytest.mark.django_db
def test_copy_article_source_untouched(archive: Archive) -> None:
    articles = archive.articles
    articles.save(
        Article(ulid="01SRC", title="Original", collection_id="FOTOS", ref_code="F1"),
        0,
        changed_by="tester",
    )
    copy_article(archive, "01SRC", changed_by="tester")
    original = articles.load("01SRC").article
    assert original.ref_code == "F1"  # source Signatur intact
    assert original.title == "Original"


# ---------------------------------------------------------------------------
# hard_delete_article — removes canonical then drops the index row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hard_delete_article_removes_index_row(archive: Archive) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = archive.articles
    save_article(
        archive,
        articles.load("01FOTO").article,
        articles.load("01FOTO").version,
        changed_by="tester",
    )
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    result = hard_delete_article(archive, "01FOTO", archive.articles.load("01FOTO").version)
    assert result.index_updated is True
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


@pytest.mark.django_db
def test_hard_delete_article_stands_when_the_remote_delete_cannot_be_enqueued(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.articles as articles_mod

    def boom(_ulid: str) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(articles_mod, "enqueue_mirror_delete_article", boom)

    result = hard_delete_article(archive, "01FOTO", archive.articles.load("01FOTO").version)

    assert (result.index_updated, list(archive.articles.list_ulids())) == (True, [])


# ---------------------------------------------------------------------------
# Sync-failure path — canonical write STANDS, job enqueued, index_updated=False
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_index_failure_stands_canonical_and_enqueues(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the synchronous index update to fail at the SERVICE seam. The canonical write must
    stand, a reference reindex job must be enqueued, and the result must carry
    index_updated=False (so the UI shows 'Sichtbarkeitsänderung noch nicht wirksam')."""
    import bundesarchiv.app.articles as articles_mod

    enqueued: list[str] = []

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("index down")

    monkeypatch.setattr(articles_mod, "index_article", boom)
    monkeypatch.setattr(articles_mod, "enqueue_reindex_article", lambda ulid: enqueued.append(ulid))

    articles = archive.articles
    stored = articles.load("01FOTO")
    result = save_article(archive, stored.article, stored.version, changed_by="tester")

    assert result.index_updated is False
    assert result.version == 2  # canonical write STOOD despite the index failure
    assert enqueued == ["01FOTO"]  # a reference job was enqueued for retry
    # canonical truth is durable at the new version:
    assert archive.articles.load("01FOTO").version == 2


@pytest.mark.django_db
def test_save_article_swallows_enqueue_failure_after_index_failure(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue-down at enqueue time must not fail a request whose canonical write already stood: when
    BOTH the synchronous index update AND the retry enqueue raise, save_article still succeeds with
    index_updated=False and no exception escapes (mirrors _enqueue_mirror's swallow policy)."""
    import bundesarchiv.app.articles as articles_mod

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("index down")

    def enqueue_boom(_ulid: str) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(articles_mod, "index_article", boom)
    monkeypatch.setattr(articles_mod, "enqueue_reindex_article", enqueue_boom)

    articles = archive.articles
    stored = articles.load("01FOTO")
    result = save_article(archive, stored.article, stored.version, changed_by="tester")

    assert result.index_updated is False
    assert result.version == 2  # canonical write STOOD despite both failures
    assert archive.articles.load("01FOTO").version == 2


@pytest.mark.django_db
def test_save_collection_swallows_enqueue_failure_after_index_failure(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.collections as collections_mod

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("index down")

    def enqueue_boom(_ulid: str) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(collections_mod, "index_subtree", boom)
    monkeypatch.setattr(collections_mod, "enqueue_reindex_subtree", enqueue_boom)

    stored = archive.collections.load("FOTOS")
    result = save_collection(archive, stored.collection, stored.version, changed_by="tester")

    assert (result.version, result.index_updated) == (2, False)
    assert archive.collections.load("FOTOS").version == 2


@pytest.mark.django_db(transaction=True)
def test_save_article_gives_up_on_a_held_index_lock_and_enqueues(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A save whose index update cannot get the index-writer lock within the sync bound (a rebuild
    holds it) returns index_updated=False and queues the retry instead of waiting the holder out."""
    from django.db import connection, transaction

    import bundesarchiv.app.articles as articles_mod
    from bundesarchiv.index.indexer import _take_writer_lock

    enqueued: list[str] = []
    monkeypatch.setattr(articles_mod, "enqueue_reindex_article", enqueued.append)
    monkeypatch.setattr(articles_mod, "SYNC_LOCK_TIMEOUT_MS", 100)
    held, release = threading.Event(), threading.Event()

    def hold_lock() -> None:
        try:
            with transaction.atomic():
                _take_writer_lock()
                held.set()
                release.wait(timeout=5)
        finally:
            connection.close()

    stored = archive.articles.load("01FOTO")
    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_lock)
        assert held.wait(timeout=5)
        started = time.monotonic()
        result = save_article(archive, stored.article, stored.version, changed_by="tester")
        elapsed = time.monotonic() - started
        release.set()
        holder.result()

    assert result.index_updated is False
    assert enqueued == ["01FOTO"]
    assert elapsed < 2


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — article unpublish (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_unpublishing_article_via_service_hides_it_next_search(
    archive: Archive,
) -> None:
    """Publish -> index via the service -> Public sees it. Unpublish (DRAFT) THROUGH the service.
    The member/public's very NEXT search must exclude it. rebuild() is FORBIDDEN here — only the
    production save_article entry point may touch the index."""
    articles = archive.articles
    save_article(
        archive,
        articles.load("01FOTO").article,
        articles.load("01FOTO").version,
        changed_by="tester",
    )
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)

    stored = articles.load("01FOTO")
    unpublished = Article(
        ulid="01FOTO",
        title="Öffentliches Foto",
        collection_id="FOTOS",
        lifecycle=Lifecycle.DRAFT,  # unpublished -> archivist-only
        date=EdtfDate("1965"),
    )
    save_article(archive, unpublished, stored.version, changed_by="tester")

    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # gone for Public
    assert "Öffentliches Foto" not in _pub_titles(PLAIN_MEMBER)  # gone for Members too


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — collection audience narrowing (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_narrowing_collection_audience_via_service_hides_descendants(
    archive: Archive,
) -> None:
    """Index the descendant article (PUBLIC via FOTOS). Narrow FOTOS to MEMBERS THROUGH
    save_collection. The public member's next search must no longer return the descendant.
    rebuild() is FORBIDDEN — only save_collection may touch the index."""
    articles = archive.articles
    save_article(
        archive,
        articles.load("01FOTO").article,
        articles.load("01FOTO").version,
        changed_by="tester",
    )
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)  # visible to Public via FOTOS=PUBLIC

    collections = archive.collections
    stored = collections.load("FOTOS")
    result = save_collection(
        archive,
        Collection(
            ulid="FOTOS",
            name="Fotos",
            parent_id="ROOT",
            audience=Audience(AudienceTier.MEMBERS),  # narrow PUBLIC -> MEMBERS
        ),
        stored.version,
        changed_by="tester",
    )

    assert result.index_updated is True
    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # descendant hidden from Public
    assert "Öffentliches Foto" in _pub_titles(PLAIN_MEMBER)  # still visible to Members


# ---------------------------------------------------------------------------
# Thumbnail enqueue — save/create enqueue a thumbnail job for IMAGE media only (Part 4.3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_enqueues_thumbnail_for_image_media(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An image MediaRef on a saved Article enqueues a thumbnail job for it; a non-image one
    does not (the job would no-op anyway, but the service avoids enqueuing obvious non-images)."""
    import bundesarchiv.app.articles as articles_mod

    enqueued: list[tuple[str, str]] = []
    monkeypatch.setattr(
        articles_mod, "enqueue_generate_thumbnail", lambda *job: enqueued.append(job)
    )

    articles = archive.articles
    image = articles.add_media(
        "01FOTO", "scan.jpg", io.BytesIO(b"\xff\xd8\xff-fake"), media_type="image/jpeg"
    )
    doc = articles.add_media(
        "01FOTO", "notes.pdf", io.BytesIO(b"%PDF-1.7"), media_type="application/pdf"
    )
    stored = articles.load("01FOTO")
    save_article(
        archive,
        Article(
            ulid="01FOTO",
            title="Öffentliches Foto",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            media=(image, doc),
        ),
        stored.version,
        changed_by="tester",
    )

    assert enqueued == [("01FOTO", image.content_hash)]  # image enqueued, PDF skipped


def test_enqueue_thumbnails_selects_image_media_by_type_and_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared enqueue helper (used by both save_article and create_article) enqueues exactly the
    image media: an ``image/*`` media_type, or a known image extension when media_type is absent —
    and nothing else. This covers the create path too (it shares this helper), without the
    chicken-and-egg of storing a blob under a not-yet-minted ULID."""
    import bundesarchiv.app.articles as articles_mod
    from bundesarchiv.domain.models import MediaRef

    enqueued: list[str] = []
    monkeypatch.setattr(
        articles_mod, "enqueue_generate_thumbnail", lambda _ulid, h: enqueued.append(h)
    )

    article = Article(
        ulid="01FOTO",
        title="Mixed media",
        collection_id="FOTOS",
        media=(
            MediaRef("a.jpg", "hash-typed-image", media_type="image/jpeg"),
            MediaRef("b.png", "hash-untyped-image", media_type=None),  # inferred by extension
            MediaRef("c.pdf", "hash-doc", media_type="application/pdf"),
            MediaRef("d.bin", "hash-unknown", media_type=None),  # unknown ext, no type
        ),
    )
    articles_mod._enqueue_thumbnails(article)

    assert enqueued == ["hash-typed-image", "hash-untyped-image"]


@pytest.mark.django_db
def test_save_article_thumbnail_enqueue_failure_does_not_break_save(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.articles as articles_mod

    def boom(_ulid: str, _content_hash: str) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(articles_mod, "enqueue_generate_thumbnail", boom)

    articles = archive.articles
    image = articles.add_media(
        "01FOTO", "scan.jpg", io.BytesIO(b"\xff\xd8\xff-fake"), media_type="image/jpeg"
    )
    stored = articles.load("01FOTO")
    result = save_article(
        archive, replace(stored.article, media=(image,)), stored.version, changed_by="tester"
    )

    saved = articles.load("01FOTO")
    assert (saved.version, saved.article.media) == (result.version, (image,))


# ---------------------------------------------------------------------------
# The push enqueue (ADR 0020) — one reference job per saved Article or Collection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_enqueues_one_push_of_the_article(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.articles as articles_mod

    pushed: list[str] = []
    monkeypatch.setattr(articles_mod, "enqueue_mirror_push", pushed.append)

    stored = archive.articles.load("01FOTO")
    save_article(archive, stored.article, stored.version, changed_by="tester")

    assert pushed == ["01FOTO"]


@pytest.mark.django_db
def test_create_article_enqueues_the_push_of_the_new_article(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.articles as articles_mod

    pushed: list[str] = []
    monkeypatch.setattr(articles_mod, "enqueue_mirror_push", pushed.append)

    result = create_article(archive, title="Neu", collection_id="FOTOS", changed_by="tester")

    assert pushed == [result.ulid]


@pytest.mark.django_db
def test_save_collection_enqueues_one_push_of_the_collection(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bundesarchiv.app.collections as collections_mod

    pushed: list[str] = []
    monkeypatch.setattr(collections_mod, "enqueue_mirror_push", pushed.append)

    stored = archive.collections.load("FOTOS")
    save_collection(archive, stored.collection, stored.version, changed_by="tester")

    assert pushed == ["FOTOS"]


@pytest.mark.django_db
def test_save_article_mirror_enqueue_failure_does_not_break_save(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mirror-enqueue failure must NOT fail the request (same discipline as the index-sync retry:
    mirror lag is invisible-by-design and the reconcile heals it). The canonical write stands."""
    import bundesarchiv.app.articles as articles_mod

    def boom(_ulid: str) -> None:
        raise RuntimeError("queue down")

    monkeypatch.setattr(articles_mod, "enqueue_mirror_push", boom)

    articles = archive.articles
    stored = articles.load("01FOTO")
    result = save_article(archive, stored.article, stored.version, changed_by="tester")

    assert result.version == 2  # save succeeded despite the mirror-enqueue failure
    assert archive.articles.load("01FOTO").version == 2


@pytest.mark.django_db(transaction=True)
def test_save_collection_gives_up_on_a_held_index_lock_and_enqueues(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Bestand save path has the same bound as the Article save path."""
    from django.db import connection, transaction

    import bundesarchiv.app.collections as collections_mod
    from bundesarchiv.index.indexer import _take_writer_lock

    enqueued: list[str] = []
    monkeypatch.setattr(collections_mod, "enqueue_reindex_subtree", enqueued.append)
    monkeypatch.setattr(collections_mod, "SYNC_LOCK_TIMEOUT_MS", 100)
    held, release = threading.Event(), threading.Event()

    def hold_lock() -> None:
        try:
            with transaction.atomic():
                _take_writer_lock()
                held.set()
                release.wait(timeout=5)
        finally:
            connection.close()

    stored = archive.collections.load("FOTOS")
    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_lock)
        assert held.wait(timeout=5)
        started = time.monotonic()
        result = save_collection(archive, stored.collection, stored.version, changed_by="tester")
        elapsed = time.monotonic() - started
        release.set()
        holder.result()

    assert result.index_updated is False
    assert enqueued == ["FOTOS"]
    assert elapsed < 2
