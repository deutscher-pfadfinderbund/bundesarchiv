"""Page text (ADR 0023): a word on a page reaches an Article only through the viewer's scope.

Every restricted Article below carries a word that exists nowhere but on a page of its own file,
so each absence is the scope's. Page rows are stored inside each test (they roll back with it);
the differential tests take their baseline before storing them.

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see
``test_leaks_decades.py``).
"""

import io
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.index import indexer
from bundesarchiv.index.models import MediaText
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_OPEN, _MEMBERS, _BOARD = "TX_OPEN", "TX_MEMBERS", "TX_BOARD"

_PUBLIC = "TX_PUBLIC"  # two files; a record without any page word
_RECORD = "TX_RECORD"  # "Kochtopf" in its record; a scanned file and an unreadable one
_SHARED = "TX_SHARED"  # public; its file is also on _SHARED_HIDDEN
_SHARED_HIDDEN = "TX_SHARED_HIDDEN"
_MEMBER_ONLY = "TX_MEMBER_ONLY"
_GROUP = "TX_GROUP"
_DRAFT = "TX_DRAFT"
_TEMPLATE = "TX_TEMPLATE"
_TRASH = "TX_TRASH"
_ORPHAN = "TX_ORPHAN"

_SHARED_BYTES = b"one file on two Articles"

# (ulid, index of the file in its media) -> the file's page texts; () is the unreadable-file marker.
_PAGES: Mapping[tuple[str, int], tuple[str, ...]] = {
    (_PUBLIC, 0): ("Lagerfeuer", "nichts", "Lagerfeuer Kochtopf Kochtopf Kochtopf"),
    (_PUBLIC, 1): ("Lagerfeuer",),
    (_RECORD, 0): ("", ""),
    (_RECORD, 1): (),
    (_SHARED, 0): ("Lagerfeuer Gemeinschaftsseite",),
    (_MEMBER_ONLY, 0): ("Lagerfeuer Mitgliederseite",),
    (_GROUP, 0): ("Lagerfeuer Vorstandsseite",),
    (_DRAFT, 0): ("Lagerfeuer Entwurfsseite",),
    (_TEMPLATE, 0): ("Lagerfeuer Vorlagenseite",),
    (_TRASH, 0): ("Lagerfeuer Papierkorbseite",),
    (_ORPHAN, 0): ("Lagerfeuer Waisenseite",),
}


@dataclass(frozen=True, slots=True)
class _Corpus:
    store: InMemoryObjectStore
    media: Mapping[str, tuple[str, ...]]  # ulid -> its files' content hashes, in media order


def _articles() -> tuple[tuple[Article, tuple[tuple[str, bytes], ...]], ...]:
    """Each Article with its files as (name, bytes); none carries a page word in its record."""
    hidden = {"tags": ("verborgen",)}
    return (
        (make_article(_PUBLIC, collection_id=_OPEN, title="Abendbericht"), (("a.pdf", b"a"), ("b.pdf", b"b"))),
        (make_article(_RECORD, collection_id=_OPEN, title="Kochtopf und Rezept"), (("scan.pdf", b"s"), ("lock.pdf", b"l"))),
        (make_article(_SHARED, collection_id=_OPEN, title="Geteilt"), (("shared.pdf", _SHARED_BYTES),)),
        (make_article(_SHARED_HIDDEN, collection_id=_BOARD, title="Auch geteilt", **hidden), (("shared.pdf", _SHARED_BYTES),)),
        (make_article(_MEMBER_ONLY, collection_id=_MEMBERS, title="Akte", **hidden), (("m.pdf", b"m"),)),
        (make_article(_GROUP, collection_id=_BOARD, title="Protokoll", **hidden), (("g.pdf", b"g"),)),
        (make_article(_DRAFT, collection_id=_OPEN, title="Entwurf", lifecycle=Lifecycle.DRAFT, **hidden), (("d.pdf", b"d"),)),
        (make_article(_TEMPLATE, collection_id=_OPEN, title="Vorlage", lifecycle=Lifecycle.DRAFT, template=True, **hidden), (("t.pdf", b"t"),)),
        (make_article(_TRASH, collection_id=_OPEN, title="Weggeworfen", **hidden), (("p.pdf", b"p"),)),
        (make_article(_ORPHAN, collection_id="TX_GHOST", title="Verwaist", **hidden), (("o.pdf", b"o"),)),
    )  # fmt: skip


def _unique(ulid: str, blob: bytes) -> bytes:
    return blob if blob == _SHARED_BYTES else ulid.encode() + blob


def _build() -> _Corpus:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    collections.save(
        Collection(_OPEN, "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="t"
    )
    collections.save(
        Collection(_MEMBERS, "Mitglieder", audience=Audience(AudienceTier.MEMBERS)),
        0,
        changed_by="t",
    )
    collections.save(
        Collection(_BOARD, "Vorstand", audience=Audience(AudienceTier.GROUPS, ("vorstand",))),
        0,
        changed_by="t",
    )
    repo = ArticleRepository(store)
    media: dict[str, tuple[str, ...]] = {}
    for article, files in _articles():
        refs = [
            repo.add_media(article.ulid, name, io.BytesIO(_unique(article.ulid, blob)))
            for name, blob in files
        ]
        if article.ulid == _PUBLIC:  # media order against hash order, so an order by hash shows
            refs.sort(key=lambda ref: ref.content_hash, reverse=True)
        repo.save(replace(article, media=tuple(refs)), 0, changed_by="t")
        media[article.ulid] = tuple(ref.content_hash for ref in refs)
    repo.mark_deleted(repo.load(_TRASH).article, 1, changed_by="t")
    indexer.rebuild(store)
    return _Corpus(store, media)


@pytest.fixture(scope="module")
def _indexed(django_db_setup: None, django_db_blocker: pytest.FixtureRequest) -> Iterator[_Corpus]:
    yield from fixtures.indexed_corpus(django_db_blocker, _build)


@pytest.fixture
def corpus(_indexed: _Corpus, db: None) -> _Corpus:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""
    return _indexed


def _store_pages(corpus: _Corpus) -> None:
    for (ulid, index), pages in _PAGES.items():
        indexer.store_media_text(corpus.media[ulid][index], pages)


def _stored_hashes() -> set[str]:
    return set(MediaText.objects.values_list("content_hash", flat=True))


# --- rebuild keeps the text of every file a row names -------------------------------------------


def test_rebuild_drops_the_text_no_row_names_and_keeps_the_papierkorb_text(corpus: _Corpus) -> None:
    _store_pages(corpus)
    indexer.store_media_text("f" * 64, ("Lagerfeuer",))

    indexer.rebuild(corpus.store)

    assert _stored_hashes() == {corpus.media[ulid][index] for ulid, index in _PAGES}
