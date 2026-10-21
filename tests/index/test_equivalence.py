"""SQL ≡ ``can_view`` (ADR 0012) over the article audience x parent audience x lifecycle grid.

The one allowed gap: a fail-closed row is index-visible to the Archivist but ``can_view``-denied.
"""

from collections.abc import Iterator, Mapping

import pytest
from pytest_django.plugin import DjangoDbBlocker
from tests.index import fixtures

from bundesarchiv.domain.access import can_view
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import SearchFilters, search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

GROUP_A = "gruppe-a"
GROUP_B = "gruppe-b"

# Every group-membership shape that can flip a GROUPS decision.
_VIEWERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member()", Member(())),
    ("member(a)", Member((GROUP_A,))),
    ("member(b)", Member((GROUP_B,))),
    ("member(a,b)", Member((GROUP_A, GROUP_B))),
    ("archivist", Archivist()),
)

# --- Grid axes --------------------------------------------------------------

_ARTICLE_AUDIENCES: tuple[tuple[str, Audience | None], ...] = (
    ("apub", Audience(AudienceTier.PUBLIC)),
    ("amem", Audience(AudienceTier.MEMBERS)),
    ("agra", Audience(AudienceTier.GROUPS, (GROUP_A,))),
    ("agrab", Audience(AudienceTier.GROUPS, (GROUP_A, GROUP_B))),
    ("ainh", None),
)

# ``None`` inherits the silent root: the MEMBERS default.
_PARENT_AUDIENCES: tuple[tuple[str, Audience | None], ...] = (
    ("ppub", Audience(AudienceTier.PUBLIC)),
    ("pmem", Audience(AudienceTier.MEMBERS)),
    ("pgrb", Audience(AudienceTier.GROUPS, (GROUP_B,))),
    ("pinh", None),
)

_LIFECYCLES: tuple[tuple[str, Lifecycle], ...] = (
    ("draft", Lifecycle.DRAFT),
    ("pub", Lifecycle.PUBLISHED),
)

_ROOT_ULID = ULID("GRID_ROOT")

# One media_type shared by every grid article, so its facet count per viewer must equal the size of
# the whole can_view-visible set — a single dimension-independent number for the aggregate check.
_GRID_MEDIA_TYPE = "Rasterakte"


def _parent_ulid(parent_tag: str) -> ULID:
    return ULID(f"GRID_PARENT_{parent_tag}")


def _leaf_ulid(parent_tag: str) -> ULID:
    return ULID(f"GRID_LEAF_{parent_tag}")


def _build_grid_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(
        Collection(ulid=_ROOT_ULID, name="Grid-Wurzel", parent_id=None), 0, changed_by="tester"
    )
    for parent_tag, parent_audience in _PARENT_AUDIENCES:
        collections.save(
            Collection(
                ulid=_parent_ulid(parent_tag),
                name=f"Eltern {parent_tag}",
                parent_id=_ROOT_ULID,
                audience=parent_audience,
            ),
            0,
            changed_by="tester",
        )
        # The leaf is always silent (inherit): the article-vs-parent interplay is the axis, so the
        # leaf adds no third audience of its own — an article inheriting falls straight to the parent.
        collections.save(
            Collection(
                ulid=_leaf_ulid(parent_tag),
                name=f"Blatt {parent_tag}",
                parent_id=_parent_ulid(parent_tag),
            ),
            0,
            changed_by="tester",
        )

    for article in _grid_articles():
        articles.save(article, 0, changed_by="tester")
    return store


def _grid_articles() -> Iterator[Article]:
    """Ulids encode the grid coordinates, so a mismatch names the exact cell."""
    for parent_tag, _parent_audience in _PARENT_AUDIENCES:
        for art_tag, art_audience in _ARTICLE_AUDIENCES:
            for life_tag, lifecycle in _LIFECYCLES:
                ulid = ULID(f"GRID_{parent_tag}_{art_tag}_{life_tag}")
                yield Article(
                    ulid=ulid,
                    title=f"Rasterartikel {ulid}",
                    collection_id=_leaf_ulid(parent_tag),
                    lifecycle=lifecycle,
                    audience=art_audience,
                    media_type=_GRID_MEDIA_TYPE,
                )


def _collection_lookup(store: InMemoryObjectStore) -> Mapping[ULID, Collection]:
    return {c.ulid: c for c in CollectionRepository(store).load_all()}


def _build_grid() -> _Grid:
    store = _build_grid_store()
    return _Grid(store=store, report=indexer.rebuild(store))


@pytest.fixture(scope="module")
def grid(django_db_setup: None, django_db_blocker: DjangoDbBlocker) -> Iterator[_Grid]:
    yield from fixtures.indexed_corpus(django_db_blocker, _build_grid)


class _Grid:
    def __init__(self, store: InMemoryObjectStore, report: indexer.RebuildReport) -> None:
        self.store = store
        self.report = report
        self.lookup = _collection_lookup(store)
        self.articles = tuple(
            ArticleRepository(store).load(ULID(u)).article for u in _all_ulids(store)
        )

    def can_view_ulids(self, viewer: Viewer) -> set[str]:
        """Catch only ``DomainError`` (what ``can_view`` fails closed on): anything else must fail
        the guard, not shrink the expected set."""
        visible: set[str] = set()
        for article in self.articles:
            try:
                chain: ResolvedChain = resolve_chain(article.collection_id, self.lookup)
            except DomainError:
                continue
            if can_view(viewer, article, chain):
                visible.add(article.ulid)
        return visible


def _all_ulids(store: InMemoryObjectStore) -> tuple[str, ...]:
    return tuple(ArticleRepository(store).list_ulids())


@pytest.fixture
def corpus(grid: _Grid, db: None) -> _Grid:
    return grid


def _search_ulids(viewer: Viewer) -> set[str]:
    """The grid must fit one page: ``search`` clamps ``page_size`` to 200."""
    return {hit.ulid for hit in search(viewer, page_size=1000).hits}


# ===========================================================================
# The grid: set(search ulids) == {can_view ulids} per viewer (with carve-out).
# ===========================================================================


@pytest.mark.django_db
def test_grid_has_expected_shape(corpus: _Grid) -> None:
    """A shrunk grid or a fail-closed row would silently weaken every equivalence test below."""
    assert len(corpus.articles) == 40
    assert corpus.report.indexed == 40
    assert corpus.report.failed_closed == ()
    assert _search_ulids(Archivist()) == {a.ulid for a in corpus.articles}


@pytest.mark.django_db
def test_search_equals_can_view_per_viewer(corpus: _Grid) -> None:
    failed_closed = set(corpus.report.failed_closed)
    mismatches: list[str] = []
    for label, viewer in _VIEWERS:
        got = _search_ulids(viewer)
        expected = corpus.can_view_ulids(viewer)
        # The fail-closed carve-out (module docstring); a no-op on this grid.
        if isinstance(viewer, Archivist):
            expected = expected | failed_closed
        leaked = got - expected  # in search, not authorized: a real data leak
        missing = expected - got  # authorized, not returned: an availability defect
        if leaked:
            mismatches.append(f"[{label}] LEAKED (search but not can_view): {sorted(leaked)}")
        if missing:
            mismatches.append(f"[{label}] MISSING (can_view but not search): {sorted(missing)}")
    assert not mismatches, "SQL ≢ can_view — offending (viewer, articles) pairs:\n" + "\n".join(
        mismatches
    )


# ===========================================================================
# Grid facet totals: aggregate counts derived from the can_view-visible set.
# ===========================================================================


@pytest.mark.django_db
def test_grid_facet_total_equals_can_view_count_per_viewer(corpus: _Grid) -> None:
    """No aggregate tallies an out-of-scope row."""
    failed_closed = set(corpus.report.failed_closed)
    mismatches: list[str] = []
    for label, viewer in _VIEWERS:
        expected_ulids = corpus.can_view_ulids(viewer)
        if isinstance(viewer, Archivist):
            expected_ulids = expected_ulids | failed_closed
        expected_n = len(expected_ulids)

        page = search(viewer, page_size=1000)
        if page.total != expected_n:
            mismatches.append(f"[{label}] total={page.total} != can_view count={expected_n}")
        media = {fc.value: fc.count for fc in page.facets["media_type"]}
        got_media = media.get(_GRID_MEDIA_TYPE, 0)
        if got_media != expected_n:
            mismatches.append(
                f"[{label}] media_type[{_GRID_MEDIA_TYPE}]={got_media} != can_view count={expected_n}"
            )
        # Grid articles carry no date, so the dateless count is the whole visible set too.
        if page.dateless_count != expected_n:
            mismatches.append(
                f"[{label}] dateless_count={page.dateless_count} != can_view count={expected_n}"
            )
    assert not mismatches, "facet/total ≢ can_view count:\n" + "\n".join(mismatches)


# ===========================================================================
# Subtree-filter equivalence: a per-parent collection filter is still can_view-scoped.
# ===========================================================================


@pytest.mark.django_db
def test_grid_subtree_filter_stays_can_view_scoped(corpus: _Grid) -> None:
    mismatches: list[str] = []
    for parent_tag, _audience in _PARENT_AUDIENCES:
        subtree = {a.ulid for a in corpus.articles if a.collection_id == _leaf_ulid(parent_tag)}
        for label, viewer in _VIEWERS:
            visible = corpus.can_view_ulids(viewer)
            expected = visible & subtree
            got = {
                hit.ulid
                for hit in search(
                    viewer,
                    filters=SearchFilters(collection=_parent_ulid(parent_tag)),
                    page_size=1000,
                ).hits
            }
            if got != expected:
                mismatches.append(
                    f"[parent={parent_tag}, {label}] "
                    f"leaked={sorted(got - expected)} missing={sorted(expected - got)}"
                )
    assert not mismatches, "subtree filter ≢ can_view ∩ subtree:\n" + "\n".join(mismatches)
