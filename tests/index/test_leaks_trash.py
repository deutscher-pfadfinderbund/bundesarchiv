"""The Papierkorb's leak channels (ADR 0022): a marked Article on every search surface.

A marked Article keeps its index row with the archivist-only scope plus the mark. The normal
search, its filters, facets and counts leave it out for every viewer, the Archivist included; the
Papierkorb query lists only marked rows, and only to the Archivist. The corpus is public on
purpose: without the mark, every tier would see every row, so each absence below is the mark's.

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see
``test_leaks_decades.py``).
"""

import io
from collections.abc import Iterator
from dataclasses import replace

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import Facet, SearchFilters, SearchPage, facet_counts, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = "PK_ROOT"
_LIVE = "PK_LIVE"
_MARKED = "PK_MARKED"
_MARKED_DATELESS = "PK_MARKED_DATELESS"

_NON_ARCHIVISTS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member()", Member(())),
    ("member(vorstand)", Member(("vorstand",))),
)
_EVERY_VIEWER = (*_NON_ARCHIVISTS, ("archivist", Archivist()))

# Values only the marked rows carry, per filter and facet dimension.
_MARKED_ONLY_FILTERS = (
    SearchFilters(tag="weggeworfen"),
    SearchFilters(document_type="Abfallschrift"),
    SearchFilters(media_type="Abfallart"),
    SearchFilters(decade=1840),
    SearchFilters(dateless=True),
)
_MARKED_ONLY_FACETS: tuple[tuple[Facet, str], ...] = (
    ("tags", "weggeworfen"),
    ("document_type", "Abfallschrift"),
    ("media_type", "Abfallart"),
    ("decades", "1840"),
)


def _with_file(repo: ArticleRepository, article: Article, caption: str) -> Article:
    ref = repo.add_media(
        article.ulid, "scan.jpg", io.BytesIO(article.ulid.encode()), caption=caption
    )
    return replace(article, media=(ref,))


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection(_ROOT, "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="tester"
    )
    repo = ArticleRepository(store)
    live = make_article(
        _LIVE,
        collection_id=_ROOT,
        title="Lebendiger Bericht",
        tags=("lebend",),
        date=EdtfDate("1930"),
    )
    repo.save(_with_file(repo, live, "Aushang"), 0, changed_by="anna")
    marked = make_article(
        _MARKED,
        collection_id=_ROOT,
        title="Papierkorbfund",
        tags=("weggeworfen",),
        document_type="Abfallschrift",
        media_type="Abfallart",
        date=EdtfDate("1845"),
    )
    dateless = make_article(
        _MARKED_DATELESS, collection_id=_ROOT, title="Papierkorbfund ohne Datum"
    )
    for article in (_with_file(repo, marked, "Kehrichtnotiz"), dateless):
        repo.save(article, 0, changed_by="anna")
        repo.mark_deleted(repo.load(article.ulid).article, 1, changed_by="bernd")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


def _ulids(page: SearchPage) -> set[str]:
    return {hit.ulid for hit in page.hits}


def _facet(page: SearchPage, key: str, value: str) -> int:
    return next((fc.count for fc in page.facets[key] if fc.value == value), 0)


_TRASH = SearchFilters(deleted=True)


# --- the normal search leaves a marked Article out for everyone ------------------------------


@pytest.mark.django_db
def test_the_list_counts_and_facets_leave_marked_articles_out_for_every_viewer(
    corpus: None,
) -> None:
    for label, viewer in _EVERY_VIEWER:
        page = search(viewer, page_size=200)
        assert (_ulids(page), page.total, page.dateless_count) == ({_LIVE}, 1, 0), f"[{label}]"
        assert _facet(page, "collection", _ROOT) == 1, f"[{label}] a marked row counted"
        for key, value in _MARKED_ONLY_FACETS:
            assert _facet(page, key, value) == 0, f"[{label}] {key}={value} counted a marked row"


@pytest.mark.django_db
def test_the_facet_counts_leave_marked_articles_out_for_every_viewer(corpus: None) -> None:
    keys: tuple[Facet, ...] = ("collection", *(key for key, _ in _MARKED_ONLY_FACETS))
    for label, viewer in _EVERY_VIEWER:
        counts = facet_counts(viewer, keys)
        assert [(fc.value, fc.count) for fc in counts["collection"]] == [(_ROOT, 1)], f"[{label}]"
        for key, value in _MARKED_ONLY_FACETS:
            assert value not in {fc.value for fc in counts[key]}, f"[{label}] {key}={value}"


@pytest.mark.django_db
def test_no_text_or_filter_reaches_a_marked_article_outside_the_trash(corpus: None) -> None:
    for label, viewer in _EVERY_VIEWER:
        for text in ("Papierkorbfund", "Kehrichtnotiz"):
            assert _ulids(search(viewer, text=text)) == set(), f"[{label}] text {text!r}"
        for filters in _MARKED_ONLY_FILTERS:
            assert _ulids(search(viewer, filters=filters)) == set(), f"[{label}] {filters}"
        reached = _ulids(search(viewer, filters=SearchFilters(collection=_ROOT, has_files=True)))
        assert reached == {_LIVE}, f"[{label}]"


# --- the Papierkorb query: marked rows only, the Archivist only -------------------------------


@pytest.mark.django_db
def test_the_trash_lists_only_marked_articles_to_the_archivist(corpus: None) -> None:
    page = search(Archivist(), filters=_TRASH, page_size=200)
    assert (_ulids(page), page.total, page.dateless_count) == ({_MARKED, _MARKED_DATELESS}, 2, 1)
    assert _facet(page, "collection", _ROOT) == 2
    assert _facet(page, "tags", "lebend") == 0
    assert _ulids(search(Archivist(), text="Kehrichtnotiz", filters=_TRASH)) == {_MARKED}
    assert _ulids(search(Archivist(), text="Lebendiger", filters=_TRASH)) == set()


@pytest.mark.django_db
def test_a_trash_hit_names_who_deleted_it_and_when(corpus: None) -> None:
    marked = next(h for h in search(Archivist(), filters=_TRASH).hits if h.ulid == _MARKED)
    assert marked.deleted_by == "bernd"
    assert marked.deleted_at is not None
    (live,) = search(Archivist()).hits
    assert (live.deleted_at, live.deleted_by) == (None, None)


@pytest.mark.django_db
def test_the_trash_answers_a_non_archivist_with_an_empty_page(corpus: None) -> None:
    for label, viewer in _NON_ARCHIVISTS:
        for text in (None, "Papierkorbfund"):
            page = search(viewer, text=text, filters=_TRASH, page_size=200)
            assert (page.hits, page.total, page.dateless_count) == ((), 0, 0), f"[{label}]"
            assert not any(page.facets.values()), f"[{label}] a facet counted a marked row"
