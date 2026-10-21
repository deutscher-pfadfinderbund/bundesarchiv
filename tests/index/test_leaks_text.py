"""Page text (ADR 0023): a word on a page reaches an Article only through the viewer's scope.

Every restricted Article below carries a word that exists nowhere but on a page of its own file,
so each absence is the scope's.
"""

import io
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

import pytest
from pytest_django.plugin import DjangoDbBlocker
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import ULID, Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.models import MediaText
from bundesarchiv.index.query import SearchPage, TextPage, search
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
_TRASH = ULID("TX_TRASH")
_ORPHAN = "TX_ORPHAN"

_SHARED_BYTES = b"one file on two Articles"

_VIEWERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member", Member(())),
    ("other group", Member(("andere",))),
    ("board", Member(("vorstand",))),
    ("archivist", Archivist()),
)
_EVERYONE = frozenset(label for label, _ in _VIEWERS)
_MEMBERS_UP = _EVERYONE - {"public"}
_BOARD_UP = frozenset({"board", "archivist"})
_ARCHIVIST = frozenset({"archivist"})

# A word only on a page -> the Articles it must reach, and the viewers they reach.
_PAGE_WORDS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "Mitgliederseite": {_MEMBER_ONLY: _MEMBERS_UP},
    "Vorstandsseite": {_GROUP: _BOARD_UP},
    "Entwurfsseite": {_DRAFT: _ARCHIVIST},
    "Vorlagenseite": {_TEMPLATE: _ARCHIVIST},
    "Waisenseite": {_ORPHAN: _ARCHIVIST},
    "Papierkorbseite": {_TRASH: frozenset()},
    "Gemeinschaftsseite": {_SHARED: _EVERYONE, _SHARED_HIDDEN: _BOARD_UP},
}

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
    hidden = ("verborgen",)
    return (
        (make_article(_PUBLIC, collection_id=_OPEN, title="Abendbericht"), (("a.pdf", b"a"), ("b.pdf", b"b"))),
        (make_article(_RECORD, collection_id=_OPEN, title="Kochtopf und Rezept"), (("scan.pdf", b"s"), ("lock.pdf", b"l"))),
        (make_article(_SHARED, collection_id=_OPEN, title="Geteilt"), (("shared.pdf", _SHARED_BYTES),)),
        (make_article(_SHARED_HIDDEN, collection_id=_BOARD, title="Auch geteilt", tags=hidden), (("shared.pdf", _SHARED_BYTES),)),
        (make_article(_MEMBER_ONLY, collection_id=_MEMBERS, title="Akte", tags=hidden), (("m.pdf", b"m"),)),
        (make_article(_GROUP, collection_id=_BOARD, title="Protokoll", tags=hidden), (("g.pdf", b"g"),)),
        (make_article(_DRAFT, collection_id=_OPEN, title="Entwurf", lifecycle=Lifecycle.DRAFT, tags=hidden), (("d.pdf", b"d"),)),
        (make_article(_TEMPLATE, collection_id=_OPEN, title="Vorlage", lifecycle=Lifecycle.DRAFT, template=True, tags=hidden), (("t.pdf", b"t"),)),
        (make_article(_TRASH, collection_id=_OPEN, title="Weggeworfen", tags=hidden), (("p.pdf", b"p"),)),
        (make_article(_ORPHAN, collection_id="TX_GHOST", title="Verwaist", tags=hidden), (("o.pdf", b"o"),)),
    )  # fmt: skip


def _unique(ulid: str, blob: bytes) -> bytes:
    return blob if blob == _SHARED_BYTES else ulid.encode() + blob


def _build() -> _Corpus:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    collections.save(
        Collection(ULID(_OPEN), "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="t"
    )
    collections.save(
        Collection(ULID(_MEMBERS), "Mitglieder", audience=Audience(AudienceTier.MEMBERS)),
        0,
        changed_by="t",
    )
    collections.save(
        Collection(ULID(_BOARD), "Vorstand", audience=Audience(AudienceTier.GROUPS, ("vorstand",))),
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
def _indexed(django_db_setup: None, django_db_blocker: DjangoDbBlocker) -> Iterator[_Corpus]:
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


def _search(viewer: Viewer, text: str | None) -> SearchPage:
    return search(viewer, text=text, page_size=200)


def _ulids(page: SearchPage) -> list[str]:
    return [hit.ulid for hit in page.hits]


# --- a page word reaches an Article only inside the viewer's scope -----------------------------


def test_a_page_word_reaches_only_the_articles_the_viewer_may_see(corpus: _Corpus) -> None:
    """Below an Article's audience its page word changes nothing: hits, total, every facet and the
    dateless count equal the search without page text. A Papierkorb Article reaches no one."""
    queries = [(label, viewer, word) for label, viewer in _VIEWERS for word in _PAGE_WORDS]
    before = {(label, word): _search(viewer, word) for label, viewer, word in queries}
    _store_pages(corpus)

    for label, viewer, word in queries:
        reached = {ulid for ulid, labels in _PAGE_WORDS[word].items() if label in labels}
        page = _search(viewer, word)
        assert (set(_ulids(page)), page.total) == (reached, len(reached)), f"[{label}] {word}"
        if not reached:
            assert page == before[label, word], f"[{label}] {word} changed a count"


def test_a_hit_lists_pages_of_its_own_files_only(corpus: _Corpus) -> None:
    _store_pages(corpus)

    for label, viewer in _VIEWERS:
        for word in ("Lagerfeuer", *_PAGE_WORDS):
            for hit in _search(viewer, word).hits:
                hashes = {page.content_hash for page in hit.text_pages}
                assert hashes and hashes <= set(corpus.media[hit.ulid]), f"[{label}] {word}"


def test_a_shared_file_shows_through_the_visible_article_only(corpus: _Corpus) -> None:
    _store_pages(corpus)

    page = _search(Public(), "Gemeinschaftsseite")

    assert [(hit.ulid, hit.text_pages) for hit in page.hits] == [
        (_SHARED, (TextPage(corpus.media[_SHARED][0], 1),))
    ]


# --- what page text does not change -------------------------------------------------------------


def test_without_a_positive_page_match_a_search_is_unchanged(corpus: _Corpus) -> None:
    """A browse, a record-only word and a query without a positive word (ADR 0023) return what
    they return without page text, so no hit lists an empty page or the unreadable-file marker."""
    queries = [
        (label, viewer, text)
        for label, viewer in _VIEWERS
        for text in (None, "Rezept", "-Kochtopf", "Lagerfeuer or -Kochtopf")
    ]
    before = [_search(viewer, text) for _, viewer, text in queries]
    _store_pages(corpus)

    after = [_search(viewer, text) for _, viewer, text in queries]

    for (label, _, text), was, now in zip(queries, before, after, strict=True):
        assert now == was, f"[{label}] {text!r}"


def test_a_record_hit_outranks_a_page_hit_that_repeats_the_word(corpus: _Corpus) -> None:
    _store_pages(corpus)

    assert _ulids(_search(Public(), "Kochtopf")) == [_RECORD, _PUBLIC]


def test_a_hit_lists_its_pages_in_media_order_then_page_order(corpus: _Corpus) -> None:
    _store_pages(corpus)

    (hit,) = (h for h in _search(Public(), "Lagerfeuer").hits if h.ulid == _PUBLIC)

    first, second = corpus.media[_PUBLIC]
    assert hit.text_pages == (TextPage(first, 1), TextPage(first, 3), TextPage(second, 1))
