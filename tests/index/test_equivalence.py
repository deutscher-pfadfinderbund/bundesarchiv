"""THE §11 guard, half one: SQL ≡ ``can_view`` equivalence grid (ADR 0012).

``search`` never re-derives visibility — it rides ``_viewer_scope`` (``index.scope``), a flat-SQL
*restatement* of ``domain.access.can_view``. This test pins that the restatement is row-equivalent
to running ``can_view`` per Article: for every viewer, the ulids ``search`` returns must equal the
ulids ``can_view`` clears, over a corpus that enumerates the whole audience/lifecycle cross-product.

The grid (40 articles):

    {article audience: explicit PUBLIC, MEMBERS, GROUPS(a), GROUPS(a,b), inherit}   (5)
  x {parent audience:  explicit PUBLIC, MEMBERS, GROUPS(b), inherit}                (4)
  x {lifecycle:        DRAFT, PUBLISHED}                                            (2)
  = 40

One nested Collection pair (parent -> leaf) is built per parent-audience case; the ten
article-audience x lifecycle articles for that case live in its leaf. All four parents hang under
one shared ROOT (silent → the domain default MEMBERS), so an "inherit"-article/"inherit"-parent
combination resolves to that root default — exercising the full fall-back walk, not just a stub.

Compared against the truth for viewers {Public, Member(), Member(a), Member(b), Member(a,b),
Archivist} — every group-membership shape that can flip a GROUPS decision.

**The fail-closed carve-out (controller finding #1).** ``can_view`` denies EVERYONE, including an
Archivist, on a ``DomainError`` (an unresolvable chain yields no Audience to authorize against).
But the *index* stores such an Article as a fail-closed archivist-only row — deliberately findable
so an Archivist can repair the source (ADR 0012 / indexer docstring). So for the Archivist the two
disagree on exactly the fail-closed ulids (``RebuildReport.failed_closed``): they are index-visible
but ``can_view``-denied. The grid never produces one (every chain here resolves), so ``failed_closed``
is empty and the carve-out set is empty; ``tests/index/test_leaks.py`` pins the fail-closed row's
one-sided visibility directly on the shared corpus's ``ART_ORPHAN``. The carve-out is applied here
(rather than assumed empty) so the equivalence contract is stated in full at its natural home.
"""

from collections.abc import Iterator, Mapping

import pytest
from tests.index import fixtures

from bundesarchiv.domain.access import can_view
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    Ulid,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.index import indexer, search
from bundesarchiv.index.query import SearchFilters
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

# The two group names the grid turns on. A viewer holding ``GRUPPE_A`` clears a GROUPS(a) or
# GROUPS(a,b) rung; ``GRUPPE_B`` clears GROUPS(a,b) or a GROUPS(b) parent rung.
GRUPPE_A = "gruppe-a"
GRUPPE_B = "gruppe-b"

# The six viewers spanning every group-membership shape that can flip a GROUPS decision.
_VIEWERS: tuple[tuple[str, Viewer], ...] = (
    ("public", Public()),
    ("member()", Member(())),
    ("member(a)", Member((GRUPPE_A,))),
    ("member(b)", Member((GRUPPE_B,))),
    ("member(a,b)", Member((GRUPPE_A, GRUPPE_B))),
    ("archivist", Archivist()),
)

# --- Grid axes --------------------------------------------------------------

# Article-level audience: five cases, keyed by a short tag baked into the ulid. ``None`` = inherit.
_ARTICLE_AUDIENCES: tuple[tuple[str, Audience | None], ...] = (
    ("apub", Audience(AudienceTier.PUBLIC)),
    ("amem", Audience(AudienceTier.MEMBERS)),
    ("agra", Audience(AudienceTier.GROUPS, (GRUPPE_A,))),
    ("agrab", Audience(AudienceTier.GROUPS, (GRUPPE_A, GRUPPE_B))),
    ("ainh", None),
)

# Parent-collection audience: four cases (one nested pair each). ``None`` = inherit (→ root MEMBERS).
_PARENT_AUDIENCES: tuple[tuple[str, Audience | None], ...] = (
    ("ppub", Audience(AudienceTier.PUBLIC)),
    ("pmem", Audience(AudienceTier.MEMBERS)),
    ("pgrb", Audience(AudienceTier.GROUPS, (GRUPPE_B,))),
    ("pinh", None),
)

_LIFECYCLES: tuple[tuple[str, Lifecycle], ...] = (
    ("draft", Lifecycle.DRAFT),
    ("pub", Lifecycle.PUBLISHED),
)

_ROOT_ULID = "GRID_ROOT"

# One media_type shared by every grid article, so its facet count per viewer must equal the size of
# the whole can_view-visible set — a single dimension-independent number for the aggregate check.
_GRID_MEDIA_TYPE = "Rasterakte"


def _parent_ulid(parent_tag: str) -> Ulid:
    return f"GRID_PARENT_{parent_tag}"


def _leaf_ulid(parent_tag: str) -> Ulid:
    return f"GRID_LEAF_{parent_tag}"


def _build_grid_store() -> InMemoryObjectStore:
    """A shared ROOT with one nested parent→leaf pair per parent-audience case, and the 40
    grid articles saved through the real repositories (so ``rebuild`` sees canonical READMEs)."""
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    collections.save(Collection(ulid=_ROOT_ULID, name="Grid-Wurzel", parent_id=None))
    for parent_tag, parent_audience in _PARENT_AUDIENCES:
        collections.save(
            Collection(
                ulid=_parent_ulid(parent_tag),
                name=f"Eltern {parent_tag}",
                parent_id=_ROOT_ULID,
                audience=parent_audience,
            )
        )
        # The leaf is always silent (inherit): the article-vs-parent interplay is the axis, so the
        # leaf adds no third audience of its own — an article inheriting falls straight to the parent.
        collections.save(
            Collection(
                ulid=_leaf_ulid(parent_tag),
                name=f"Blatt {parent_tag}",
                parent_id=_parent_ulid(parent_tag),
            )
        )

    for article in _grid_articles():
        articles.save(article, 0)
    return store


def _grid_articles() -> Iterator[Article]:
    """The 40 grid articles: article-audience x parent-audience x lifecycle. Each lives in its
    parent case's leaf, with a ulid encoding its coordinates so a mismatch names the exact cell."""
    for parent_tag, _parent_audience in _PARENT_AUDIENCES:
        for art_tag, art_audience in _ARTICLE_AUDIENCES:
            for life_tag, lifecycle in _LIFECYCLES:
                ulid = f"GRID_{parent_tag}_{art_tag}_{life_tag}"
                yield Article(
                    ulid=ulid,
                    title=f"Rasterartikel {ulid}",
                    collection_id=_leaf_ulid(parent_tag),
                    lifecycle=lifecycle,
                    audience=art_audience,
                    media_type=_GRID_MEDIA_TYPE,
                )


def _collection_lookup(store: InMemoryObjectStore) -> Mapping[Ulid, Collection]:
    return {c.ulid: c for c in CollectionRepository(store).load_all()}


def _build_grid() -> _Grid:
    store = _build_grid_store()
    return _Grid(store=store, report=indexer.rebuild(store))


@pytest.fixture(scope="module")
def grid(django_db_setup: None, django_db_blocker: pytest.FixtureRequest) -> Iterator[_Grid]:
    """Build + index the 40-article grid ONCE for the whole module (search is read-only), keeping
    the in-memory store + rebuild report so the truth side can resolve each chain. Routed through
    ``fixtures.indexed_corpus`` — the single isolation mechanism, which wipes the table on module
    teardown so the committed grid never leaks into a later module. Module — not session — scope so
    the corpus never outlives this module."""
    yield from fixtures.indexed_corpus(django_db_blocker, _build_grid)


class _Grid:
    """The built grid: the store (for chain resolution on the truth side) and the rebuild report
    (for the fail-closed carve-out)."""

    def __init__(self, store: InMemoryObjectStore, report: indexer.RebuildReport) -> None:
        self.store = store
        self.report = report
        self.lookup = _collection_lookup(store)
        self.articles = tuple(ArticleRepository(store).load(u).article for u in _all_ulids(store))

    def can_view_ulids(self, viewer: Viewer) -> set[str]:
        """The truth: every grid ulid ``can_view`` clears for ``viewer`` given its resolved chain.
        A ulid whose chain does not resolve is denied to everyone (``can_view`` fails closed).
        Only ``DomainError`` reads as "invisible" — exactly the class ``can_view`` denies on; any
        other exception is a bug in the truth side and must fail the guard loudly, not silently
        shrink the expected set."""
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
    """Per-test entry: joins the session-indexed grid to the ``db`` transaction fixture."""
    return grid


def _search_ulids(viewer: Viewer) -> set[str]:
    """Every ulid ``search`` returns for ``viewer`` — one unfiltered browse, page big enough to
    hold the whole grid (40 < the 200 cap)."""
    return {hit.ulid for hit in search(viewer, page_size=1000).hits}


# ===========================================================================
# The grid: set(search ulids) == {can_view ulids} per viewer (with carve-out).
# ===========================================================================


@pytest.mark.django_db
def test_grid_has_expected_shape(corpus: _Grid) -> None:
    """Guard the grid itself: 40 articles, every chain resolves (so no fail-closed row), and the
    Archivist sees all 40 — a shrunk corpus would silently weaken every equivalence assertion."""
    assert len(corpus.articles) == 40
    assert corpus.report.indexed == 40
    assert corpus.report.failed_closed == ()
    assert _search_ulids(Archivist()) == {a.ulid for a in corpus.articles}


@pytest.mark.django_db
def test_search_equals_can_view_per_viewer(corpus: _Grid) -> None:
    """THE equivalence: for every viewer, the ulids ``search`` returns equal the ulids ``can_view``
    clears — the fail-closed carve-out (controller #1) exempting index-visible-but-can_view-denied
    fail-closed rows for the Archivist only. On mismatch the message names the offending (article,
    viewer) pairs in both directions (leaked = in search not can_view; missing = the reverse)."""
    failed_closed = set(corpus.report.failed_closed)
    mismatches: list[str] = []
    for label, viewer in _VIEWERS:
        got = _search_ulids(viewer)
        expected = corpus.can_view_ulids(viewer)
        # Carve-out: fail-closed rows are index-visible to the Archivist by spec but can_view-denied
        # to everyone. For the Archivist they are an expected (search-only) surplus; for every
        # non-Archivist they must be absent from BOTH sides (pinned in test_leaks.py). The grid
        # produces none, so ``failed_closed`` is empty and this line is a no-op here.
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
#
# The hit-set check above catches a leaked ROW. This catches a leaked AGGREGATE: a facet count that
# tallies rows the viewer can't see even when those rows never appear as hits. Every grid article
# shares one media_type, so its facet count per viewer must equal the size of the can_view-visible
# set — a single, dimension-independent number the aggregate query must not exceed or undershoot.


@pytest.mark.django_db
def test_grid_facet_total_equals_can_view_count_per_viewer(corpus: _Grid) -> None:
    """Aggregate equivalence: the single shared media_type facet's count per viewer equals the
    size of that viewer's can_view-visible set (carve-out included), so no facet aggregate tallies
    an out-of-scope row. ``total`` is checked too — the pre-pagination scoped count."""
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
        # Every grid article carries the one shared media_type, so its count = the whole visible set.
        got_media = media.get(_GRID_MEDIA_TYPE, 0)
        if got_media != expected_n:
            mismatches.append(
                f"[{label}] media_type[{_GRID_MEDIA_TYPE}]={got_media} != can_view count={expected_n}"
            )
    assert not mismatches, "facet/total ≢ can_view count:\n" + "\n".join(mismatches)


# ===========================================================================
# Subtree-filter equivalence: a per-parent collection filter is still can_view-scoped.
# ===========================================================================


@pytest.mark.django_db
def test_grid_subtree_filter_stays_can_view_scoped(corpus: _Grid) -> None:
    """A collection (subtree) filter narrows the set but never widens visibility: the filtered
    result for each parent case equals the can_view-visible articles whose chain passes through that
    parent. Pins that the filter composes with — never bypasses — the scope predicate."""
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
