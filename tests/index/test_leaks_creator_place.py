"""The Urheber and Ort filters and facets per tier: they only narrow the viewer's scope.

A creator or place value carried only by a restricted row never reaches another viewer's hits,
total or counts; a value shared across tiers counts only the rows each viewer may see. The
Papierkorb half lives in ``test_leaks_trash.py``.

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see
``test_leaks_decades.py``).
"""

from collections import Counter
from collections.abc import Callable, Iterator
from typing import NamedTuple

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import Facet, SearchFilters, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = "UO_ROOT"


class _Row(NamedTuple):
    filters: dict[str, str]  # the SearchFilters field -> this row's value
    audience: Audience
    lifecycle: Lifecycle
    seen_by: frozenset[str]  # the tiers below the Archivist that may see it


_ROWS: dict[str, _Row] = {
    "UO_PUBLIC": _Row(
        {"creator": "Hans Müller", "place": "Burg Waldeck"},
        Audience(AudienceTier.PUBLIC),
        Lifecycle.PUBLISHED,
        frozenset({"public", "member", "vorstand"}),
    ),
    "UO_MEMBER": _Row(
        {"creator": "Hans Müller", "place": "Vereinsheim"},
        Audience(AudienceTier.MEMBERS),
        Lifecycle.PUBLISHED,
        frozenset({"member", "vorstand"}),
    ),
    "UO_GROUP": _Row(
        {"creator": "Vorstandschronist", "place": "Burg Waldeck"},
        Audience(AudienceTier.GROUPS, ("vorstand",)),
        Lifecycle.PUBLISHED,
        frozenset({"vorstand"}),
    ),
    "UO_DRAFT": _Row(
        {"creator": "Entwurfsautor", "place": "Entwurfsort"},
        Audience(AudienceTier.PUBLIC),
        Lifecycle.DRAFT,
        frozenset(),
    ),
}
_FILTER_BY: dict[str, Callable[[str], SearchFilters]] = {
    "creator": lambda value: SearchFilters(creator=value),
    "place": lambda value: SearchFilters(place=value),
}
_DIMENSIONS: tuple[Facet, ...] = ("creator", "place")

_TIERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member", Member(())),
    ("member", Member(("nicht-vorstand",))),
    ("vorstand", Member(("vorstand",))),
    ("archivist", Archivist()),
)


def _visible(tier: str) -> set[str]:
    return {u for u, row in _ROWS.items() if tier == "archivist" or tier in row.seen_by}


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(Collection(_ROOT, "Wurzel"), 0, changed_by="tester")
    repo = ArticleRepository(store)
    for ulid, row in _ROWS.items():
        article = make_article(
            ulid,
            collection_id=_ROOT,
            lifecycle=row.lifecycle,
            audience=row.audience,
            creator=row.filters["creator"],
            subject_place=row.filters["place"],
        )
        repo.save(article, 0, changed_by="tester")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_each_filter_value_yields_exactly_the_viewers_rows_carrying_it(
    corpus: None, tier: str, viewer: Viewer
) -> None:
    for dimension in _DIMENSIONS:
        for value in {row.filters[dimension] for row in _ROWS.values()}:
            expected = {u for u in _visible(tier) if _ROWS[u].filters[dimension] == value}
            page = search(viewer, filters=_FILTER_BY[dimension](value), page_size=200)
            assert ({h.ulid for h in page.hits}, page.total) == (expected, len(expected)), (
                f"{dimension}={value!r}"
            )


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_each_facet_counts_only_the_viewers_rows(corpus: None, tier: str, viewer: Viewer) -> None:
    facets = search(viewer, facets=_DIMENSIONS).facets
    for dimension in _DIMENSIONS:
        expected = Counter(_ROWS[u].filters[dimension] for u in _visible(tier))
        assert {fc.value: fc.count for fc in facets[dimension]} == expected, dimension


@pytest.mark.django_db
def test_a_facet_ignores_its_own_filter_and_honours_the_other(corpus: None) -> None:
    page = search(
        Archivist(),
        filters=SearchFilters(creator="Hans Müller", place="Vereinsheim"),
        facets=("creator", "place"),
    )
    assert {h.ulid for h in page.hits} == {"UO_MEMBER"}
    assert {fc.value: fc.count for fc in page.facets["creator"]} == {"Hans Müller": 1}
    assert {fc.value: fc.count for fc in page.facets["place"]} == {
        "Burg Waldeck": 1,
        "Vereinsheim": 1,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_a_facet_under_the_other_filter_counts_only_the_viewers_rows(
    corpus: None, tier: str, viewer: Viewer
) -> None:
    pairs: tuple[tuple[Facet, Facet], ...] = (("place", "creator"), ("creator", "place"))
    for facet, other in pairs:
        for value in {row.filters[other] for row in _ROWS.values()}:
            page = search(viewer, filters=_FILTER_BY[other](value), facets=(facet,))
            expected = Counter(
                _ROWS[u].filters[facet] for u in _visible(tier) if _ROWS[u].filters[other] == value
            )
            assert {fc.value: fc.count for fc in page.facets[facet]} == expected, (
                f"{facet} under {other}={value!r}"
            )


@pytest.mark.django_db
@pytest.mark.parametrize(("tier", "viewer"), _TIERS)
def test_a_facet_ignoring_its_own_filter_counts_only_the_viewers_rows(
    corpus: None, tier: str, viewer: Viewer
) -> None:
    for facet in _DIMENSIONS:
        for value in {row.filters[facet] for row in _ROWS.values()}:
            page = search(viewer, filters=_FILTER_BY[facet](value), facets=(facet,))
            expected = Counter(_ROWS[u].filters[facet] for u in _visible(tier))
            assert {fc.value: fc.count for fc in page.facets[facet]} == expected, (
                f"{facet}={value!r}"
            )
