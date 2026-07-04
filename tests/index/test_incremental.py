"""Task 4.2 — the incremental indexer surface: ``index_article`` + ``index_subtree``.

These are the performance-sugar paths over ``rebuild`` (ADR 0014): both re-read canonical
truth at execution (reference semantics — never a payload) and route through the SAME
``build_row`` + fail-closed branch as ``rebuild``. Every case here drives a real Postgres
through an in-memory ObjectStore, so the upsert/delete + generated tsvector columns are
produced by the production code path.

The single writer coordination rule (ADR 0014 v2): every index writer takes the same
``pg_advisory_xact_lock`` inside its transaction. The serialization test lives here too.
"""

import threading

import pytest

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository


def _article(collection_id: str, ulid: str, **overrides: object) -> Article:
    defaults: dict[str, object] = {
        "ulid": ulid,
        "title": "Ein Titel",
        "collection_id": collection_id,
        "lifecycle": Lifecycle.PUBLISHED,
    }
    defaults.update(overrides)
    return Article(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def store() -> InMemoryObjectStore:
    """ROOT (Members) -> FOTOS (PUBLIC) -> AKTEN (inherits PUBLIC); three published articles
    (one under each level) plus none pre-indexed. Tests index incrementally from here."""
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
    collections.save(Collection(ulid="AKTEN", name="Akten", parent_id="FOTOS"), 0)

    articles.save(_article("ROOT", "01ROOT", title="Wurzelartikel"), 0)
    articles.save(_article("FOTOS", "01FOTO", title="Foto", date=EdtfDate("1965")), 0)
    articles.save(_article("AKTEN", "01AKTE", title="Akte"), 0)
    return store


# ---------------------------------------------------------------------------
# index_article — new / changed / deleted / broken-chain / idempotent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_index_article_inserts_a_new_row(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, "01FOTO")
    row = ArticleIndex.objects.get(ulid="01FOTO")
    assert row.tier == "PUBLIC"  # inherits PUBLIC from FOTOS
    assert row.archivist_only is False
    assert list(row.collection_ancestors) == ["FOTOS", "ROOT"]


@pytest.mark.django_db
def test_index_article_updates_a_changed_row(store: InMemoryObjectStore) -> None:
    """Re-reads canonical: an article whose audience narrowed reindexes to the new scope."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, "01ROOT")
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"

    articles = ArticleRepository(store)
    stored = articles.load("01ROOT")
    articles.save(
        Article(  # narrow to GROUPS {vorstand}
            ulid="01ROOT",
            title="Wurzelartikel",
            collection_id="ROOT",
            lifecycle=Lifecycle.PUBLISHED,
            audience=Audience(AudienceTier.GROUPS, ("vorstand",)),
        ),
        stored.version,
    )
    indexer.index_article(store, "01ROOT")

    row = ArticleIndex.objects.get(ulid="01ROOT")
    assert row.tier == "GROUPS"
    assert list(row.groups) == ["vorstand"]
    assert ArticleIndex.objects.filter(ulid="01ROOT").count() == 1  # upsert, not duplicate


@pytest.mark.django_db
def test_index_article_deletes_row_when_article_gone(store: InMemoryObjectStore) -> None:
    """The ulid is no longer in canonical -> the index row is deleted (idempotent)."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, "01FOTO")
    assert ArticleIndex.objects.filter(ulid="01FOTO").exists()

    ArticleRepository(store).hard_delete("01FOTO")
    indexer.index_article(store, "01FOTO")
    assert not ArticleIndex.objects.filter(ulid="01FOTO").exists()


@pytest.mark.django_db
def test_index_article_delete_of_missing_row_is_a_noop(store: InMemoryObjectStore) -> None:
    """Deleting a never-indexed, non-existent article does nothing and does not raise."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, "01NEVER")  # not in canonical, not in index
    assert not ArticleIndex.objects.filter(ulid="01NEVER").exists()


@pytest.mark.django_db
def test_index_article_broken_chain_writes_fail_closed_row(store: InMemoryObjectStore) -> None:
    """A dangling collection_id -> archivist-only fail-closed row, same as rebuild."""
    from bundesarchiv.index.models import ArticleIndex

    ArticleRepository(store).save(_article("GHOST", "01BAD", title="Verwaist"), 0)
    indexer.index_article(store, "01BAD")

    row = ArticleIndex.objects.get(ulid="01BAD")
    assert row.archivist_only is True
    assert row.tier is None
    assert list(row.groups) == []
    assert row.title == "Verwaist"  # still findable by an Archivist
    assert list(row.collection_ancestors) == []


@pytest.mark.django_db
def test_index_article_is_idempotent(store: InMemoryObjectStore) -> None:
    """Running twice with no canonical change yields the same single row."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_article(store, "01FOTO")
    indexer.index_article(store, "01FOTO")
    assert ArticleIndex.objects.filter(ulid="01FOTO").count() == 1


# ---------------------------------------------------------------------------
# index_subtree — descendants re-scoped, non-descendants untouched
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_index_subtree_reindexes_descendants_only(store: InMemoryObjectStore) -> None:
    """Narrowing FOTOS to MEMBERS then index_subtree(FOTOS) re-scopes FOTOS + AKTEN
    (descendants) but leaves ROOT's own article untouched (not a descendant of FOTOS)."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)  # baseline: everything indexed (allowed: setup, not the assertion)
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
    assert ArticleIndex.objects.get(ulid="01AKTE").tier == "PUBLIC"  # inherits FOTOS
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"

    collections = CollectionRepository(store)
    stored = collections.load("FOTOS")
    collections.save(
        Collection(
            ulid="FOTOS",
            name="Fotos",
            parent_id="ROOT",
            audience=Audience(AudienceTier.MEMBERS),  # narrowed PUBLIC -> MEMBERS
        ),
        stored.version,
    )

    indexer.index_subtree(store, "FOTOS")

    # Descendants re-scoped to MEMBERS.
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "MEMBERS"
    assert ArticleIndex.objects.get(ulid="01AKTE").tier == "MEMBERS"
    # Non-descendant untouched.
    assert ArticleIndex.objects.get(ulid="01ROOT").tier == "MEMBERS"


@pytest.mark.django_db
def test_index_subtree_on_root_reindexes_whole_tree(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_subtree(store, "ROOT")
    assert ArticleIndex.objects.count() == 3


@pytest.mark.django_db
def test_index_subtree_is_idempotent(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.index_subtree(store, "FOTOS")
    indexer.index_subtree(store, "FOTOS")
    assert ArticleIndex.objects.get(ulid="01FOTO")  # single row, no error
    assert ArticleIndex.objects.filter(ulid="01FOTO").count() == 1


# ---------------------------------------------------------------------------
# Advisory-lock serialization — an index writer blocks behind a held index-writer lock
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_advisory_lock_serializes_concurrent_index_writers(
    store: InMemoryObjectStore,
) -> None:
    """Deterministic, lock-SENSITIVE: the main connection opens a transaction and takes the shared
    index-writer advisory lock, then a background thread runs ``index_article`` (which must acquire
    the SAME lock inside its own transaction). While the main lock is held the background write
    CANNOT complete — it blocks; once the main transaction commits (releasing the xact lock) the
    background write proceeds and lands. Without the lock the background write would finish
    immediately, so this fails closed if the lock is ever removed.
    """
    from django.db import connection, transaction

    from bundesarchiv.index.indexer import _take_writer_lock
    from bundesarchiv.index.models import ArticleIndex

    finished = threading.Event()

    def background_index() -> None:
        indexer.index_article(store, "01FOTO")  # will block on _take_writer_lock until we release
        connection.close()
        finished.set()

    with transaction.atomic():
        _take_writer_lock()  # hold the xact-scoped lock for the whole block
        worker = threading.Thread(target=background_index)
        worker.start()
        # The background writer is blocked behind our held lock: it must NOT finish within a grace
        # window. (If the lock were absent, it would complete near-instantly and set the event.)
        assert not finished.wait(timeout=1.0), "index writer did not serialize behind the lock"
    # Our transaction committed here -> the xact lock released -> the background write can proceed.
    assert finished.wait(timeout=5.0), "index writer did not proceed after the lock released"
    worker.join()

    assert ArticleIndex.objects.filter(ulid="01FOTO").count() == 1
    assert ArticleIndex.objects.get(ulid="01FOTO").tier == "PUBLIC"
