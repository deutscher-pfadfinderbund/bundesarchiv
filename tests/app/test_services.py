"""Task 4.2 — the application-service layer (``bundesarchiv.app``): the imperative shell the
Part 4.5+ views call. Each service is a thin, explicit two-step: the canonical repo write (CAS
per ADR 0013), THEN the synchronous index update (ADR 0014). An index failure never fails the
canonical write — it enqueues a reference job and returns a ``SaveResult`` carrying
``index_updated=False`` so the UI can show the ADR-mandated specific warning.

Includes THE ADVERSARIAL STALENESS GATE (ADR 0014 §gate): a narrowing edit made through the
PRODUCTION service entry point must be reflected in the very next ``search()`` — ``rebuild()`` is
FORBIDDEN inside the gate tests.
"""

import pytest

from bundesarchiv.app import (
    create_article,
    hard_delete_article,
    save_article,
    save_collection,
)
from bundesarchiv.app.result import SaveResult
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Member, Public
from bundesarchiv.index import search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

PLAIN_MEMBER = Member(())
PUBLIC = Public()


@pytest.fixture
def store() -> InMemoryObjectStore:
    """ROOT (Members) -> FOTOS (PUBLIC); one published article under FOTOS, saved through the
    repositories but NOT yet indexed (services own the indexing)."""
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
        Article(
            ulid="01FOTO",
            title="Öffentliches Foto",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            date=EdtfDate("1965"),
        ),
        0,
    )
    return store


def _pub_titles(viewer: object) -> set[str]:
    return {hit.title for hit in search(viewer, page_size=200).hits}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# save_article — happy path indexes synchronously
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_writes_canonical_and_indexes(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = ArticleRepository(store)
    stored = articles.load("01FOTO")
    result = save_article(store, stored.article, stored.version)

    assert isinstance(result, SaveResult)
    assert result.index_updated is True
    assert result.version == 2  # stored at v1 in the fixture; save bumps to v2
    row = ArticleIndex.objects.get(ulid="01FOTO")
    assert row.tier == "PUBLIC"


@pytest.mark.django_db
def test_save_article_conflict_propagates_without_indexing(store: InMemoryObjectStore) -> None:
    """A stale expected_version raises Conflict from the repo (ADR 0013) — nothing is indexed."""
    from bundesarchiv.index.models import ArticleIndex
    from bundesarchiv.persistence.errors import Conflict

    articles = ArticleRepository(store)
    stored = articles.load("01FOTO")
    with pytest.raises(Conflict):
        save_article(store, stored.article, stored.version - 1)  # stale
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()  # no index write on failure


# ---------------------------------------------------------------------------
# create_article — mints ulid, saves, indexes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_article_mints_ulid_and_indexes(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    result = create_article(
        store,
        title="Neuer Artikel",
        collection_id="FOTOS",
        lifecycle=Lifecycle.PUBLISHED,
    )
    assert result.index_updated is True
    assert result.version == 1
    row = ArticleIndex.objects.get(ulid=result.ulid)
    assert row.title == "Neuer Artikel"
    assert row.tier == "PUBLIC"


# ---------------------------------------------------------------------------
# hard_delete_article — removes canonical then drops the index row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hard_delete_article_removes_index_row(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    articles = ArticleRepository(store)
    save_article(store, articles.load("01FOTO").article, articles.load("01FOTO").version)
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    result = hard_delete_article(store, "01FOTO")
    assert result.index_updated is True
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


# ---------------------------------------------------------------------------
# Sync-failure path — canonical write STANDS, job enqueued, index_updated=False
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_index_failure_stands_canonical_and_enqueues(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the synchronous index update to fail at the SERVICE seam. The canonical write must
    stand, a reference reindex job must be enqueued, and the result must carry
    index_updated=False (so the UI shows 'Sichtbarkeitsänderung noch nicht wirksam')."""
    import bundesarchiv.app.articles as articles_mod

    enqueued: list[str] = []

    def boom(_store: object, _ulid: str) -> None:
        raise RuntimeError("index down")

    monkeypatch.setattr(articles_mod, "index_article", boom)
    monkeypatch.setattr(articles_mod, "enqueue_reindex_article", lambda ulid: enqueued.append(ulid))

    articles = ArticleRepository(store)
    stored = articles.load("01FOTO")
    result = save_article(store, stored.article, stored.version)

    assert result.index_updated is False
    assert result.version == 2  # canonical write STOOD despite the index failure
    assert enqueued == ["01FOTO"]  # a reference job was enqueued for retry
    # canonical truth is durable at the new version:
    assert ArticleRepository(store).load("01FOTO").version == 2


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — article unpublish (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_unpublishing_article_via_service_hides_it_next_search(
    store: InMemoryObjectStore,
) -> None:
    """Publish -> index via the service -> Public sees it. Unpublish (DRAFT) THROUGH the service.
    The member/public's very NEXT search must exclude it. rebuild() is FORBIDDEN here — only the
    production save_article entry point may touch the index."""
    articles = ArticleRepository(store)
    save_article(store, articles.load("01FOTO").article, articles.load("01FOTO").version)
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)

    stored = articles.load("01FOTO")
    unpublished = Article(
        ulid="01FOTO",
        title="Öffentliches Foto",
        collection_id="FOTOS",
        lifecycle=Lifecycle.DRAFT,  # unpublished -> archivist-only
        date=EdtfDate("1965"),
    )
    save_article(store, unpublished, stored.version)

    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # gone for Public
    assert "Öffentliches Foto" not in _pub_titles(PLAIN_MEMBER)  # gone for Members too


# ---------------------------------------------------------------------------
# THE ADVERSARIAL STALENESS GATE — collection audience narrowing (rebuild FORBIDDEN)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_gate_narrowing_collection_audience_via_service_hides_descendants(
    store: InMemoryObjectStore,
) -> None:
    """Index the descendant article (PUBLIC via FOTOS). Narrow FOTOS to MEMBERS THROUGH
    save_collection. The public member's next search must no longer return the descendant.
    rebuild() is FORBIDDEN — only save_collection may touch the index."""
    articles = ArticleRepository(store)
    save_article(store, articles.load("01FOTO").article, articles.load("01FOTO").version)
    assert "Öffentliches Foto" in _pub_titles(PUBLIC)  # visible to Public via FOTOS=PUBLIC

    collections = CollectionRepository(store)
    stored = collections.load("FOTOS")
    result = save_collection(
        store,
        Collection(
            ulid="FOTOS",
            name="Fotos",
            parent_id="ROOT",
            audience=Audience(AudienceTier.MEMBERS),  # narrow PUBLIC -> MEMBERS
        ),
        stored.version,
    )

    assert result.index_updated is True
    assert "Öffentliches Foto" not in _pub_titles(PUBLIC)  # descendant hidden from Public
    assert "Öffentliches Foto" in _pub_titles(PLAIN_MEMBER)  # still visible to Members


# ---------------------------------------------------------------------------
# Thumbnail enqueue — save/create enqueue a thumbnail job for IMAGE media only (Part 4.3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_article_enqueues_thumbnail_for_image_media(
    store: InMemoryObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An image MediaRef on a saved Article enqueues a content-hash thumbnail job; a non-image one
    does not (the job would no-op anyway, but the service avoids enqueuing obvious non-images)."""
    import bundesarchiv.app.articles as articles_mod

    enqueued: list[str] = []
    monkeypatch.setattr(articles_mod, "enqueue_generate_thumbnail", lambda h: enqueued.append(h))

    articles = ArticleRepository(store)
    image = articles.add_media("01FOTO", "scan.jpg", b"\xff\xd8\xff-fake", media_type="image/jpeg")
    doc = articles.add_media("01FOTO", "notes.pdf", b"%PDF-1.7", media_type="application/pdf")
    stored = articles.load("01FOTO")
    save_article(
        store,
        Article(
            ulid="01FOTO",
            title="Öffentliches Foto",
            collection_id="FOTOS",
            lifecycle=Lifecycle.PUBLISHED,
            media=(image, doc),
        ),
        stored.version,
    )

    assert enqueued == [image.content_hash]  # image enqueued, PDF skipped


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
    monkeypatch.setattr(articles_mod, "enqueue_generate_thumbnail", lambda h: enqueued.append(h))

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
