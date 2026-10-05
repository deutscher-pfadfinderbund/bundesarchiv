"""Task 8 — viewer-scoped ``search``: text, filters, facets, sort, pagination.

Every test runs against a real Postgres (the migrated test DB) over the shared corpus in
``tests/index/fixtures.py`` (a 3-level collection tree, 12 articles spanning tiers, groups,
lifecycles, dates, tags). The corpus is indexed ONCE per module via ``rebuild`` — search is
read-only, so the rows are shared read-only across the module's cases.

The security spine of these tests: the base queryset is ``_viewer_scope(viewer)``, so every
count, facet and hit must reflect exactly what that viewer may see. Per-viewer expected totals
come straight from ``fixtures.EXPECTED_VISIBILITY`` (Public 5, plain Member 8, vorstand Member
10, Archivist 12) — the same ground truth Task 9's grid pins.
"""

import datetime
from collections.abc import Iterator

import pytest
from tests._articles import make_article
from tests.index import fixtures
from tests.index.fixtures import (
    ARCHIVIST,
    PLAIN_MEMBER,
    PUBLIC,
    VORSTAND_MEMBER,
)

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection
from bundesarchiv.index import indexer
from bundesarchiv.index.query import _MAX_PAGE_SIZE, Facet, SearchFilters, SearchPage, search


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    """Build + index the shared corpus once for the whole module (search never mutates), routed
    through ``fixtures.indexed_corpus`` — the single isolation mechanism, which wipes the table on
    module teardown so the committed corpus never leaks into a later module."""
    yield from fixtures.indexed_corpus(django_db_blocker, fixtures.build_index)


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


def _ulids(page: SearchPage) -> set[str]:
    return {hit.ulid for hit in page.hits}


def _facet_map(page: SearchPage, key: str) -> dict[str, int]:
    return {fc.value: fc.count for fc in page.facets[key]}


# ===========================================================================
# Viewer scoping — the security spine: totals per viewer over the whole corpus.
# ===========================================================================


@pytest.mark.django_db
def test_public_sees_only_public_published(corpus: None) -> None:
    page = search(PUBLIC)
    assert page.total == 5
    assert _ulids(page) == {
        "ART_PUBFOTO",
        "ART_PUBLAGER",
        "ART_PUBHAUS",
        "ART_PUBKARTE",
        "ART_PUBPLAKAT",
    }


@pytest.mark.django_db
def test_plain_member_sees_public_and_members(corpus: None) -> None:
    page = search(PLAIN_MEMBER)
    assert page.total == 8
    assert "ART_MEMAKTE" in _ulids(page)
    assert "ART_GRPPROT" not in _ulids(page)  # a GROUPS row a plain member can't clear


@pytest.mark.django_db
def test_vorstand_member_also_sees_its_group(corpus: None) -> None:
    page = search(VORSTAND_MEMBER)
    assert page.total == 10
    assert {"ART_GRPPROT", "ART_GRPBESCH"} <= _ulids(page)


@pytest.mark.django_db
def test_archivist_sees_everything_including_draft_and_orphan(corpus: None) -> None:
    page = search(ARCHIVIST, page_size=200)
    assert page.total == 12
    assert {"ART_DRAFT", "ART_ORPHAN"} <= _ulids(page)


# ===========================================================================
# Text match — German FTS behaviour (ADR 0011 pinned: stem + umlaut fold).
# ===========================================================================


@pytest.mark.django_db
def test_text_is_umlaut_insensitive(corpus: None) -> None:
    """Umlaut-less typing finds an umlaut document (unaccent): 'Baume' -> 'Bäume'."""
    page = search(PUBLIC, text="Baume")
    assert "ART_PUBHAUS" in _ulids(page)  # "Bäume vor dem Haus"


@pytest.mark.django_db
def test_all_stopword_query_does_not_crash(corpus: None) -> None:
    """A query that parses to an EMPTY tsquery (all stopwords) must not raise — the NULLIF guard
    in the prefix wrapper turns ''||':*' into the empty tsquery, not the invalid ':*'."""
    page = search(PUBLIC, text="und der die")
    assert isinstance(page.total, int)  # ran without error


@pytest.mark.django_db
def test_text_ranks_the_best_match_first_within_scope(corpus: None) -> None:
    """'Fahrten' is in PUBFOTO's title and tag but only in PUBKARTE's tag, so PUBFOTO ranks
    first; the member-only MEMNOTIZ matches too, but only for a Member."""
    assert [h.ulid for h in search(PUBLIC, text="Fahrten").hits] == [
        "ART_PUBFOTO",
        "ART_PUBKARTE",
    ]
    assert "ART_MEMNOTIZ" in _ulids(search(PLAIN_MEMBER, text="Fahrten"))


# ===========================================================================
# Subtree collection filter (leaf + mid + root via collection_ancestors).
# ===========================================================================


@pytest.mark.django_db
def test_collection_filter_leaf(corpus: None) -> None:
    """LAGER is a leaf: only its own articles."""
    page = search(PUBLIC, filters=SearchFilters(collection="LAGER"))
    assert _ulids(page) == {"ART_PUBLAGER", "ART_PUBPLAKAT"}


@pytest.mark.django_db
def test_collection_filter_mid_includes_descendants(corpus: None) -> None:
    """FOTOS (mid) includes its LAGER descendants — subtree membership, not just direct."""
    page = search(PUBLIC, filters=SearchFilters(collection="FOTOS"))
    # FOTOS-direct public: PUBFOTO, PUBHAUS, PUBKARTE; LAGER descendants: PUBLAGER, PUBPLAKAT.
    assert _ulids(page) == {
        "ART_PUBFOTO",
        "ART_PUBHAUS",
        "ART_PUBKARTE",
        "ART_PUBLAGER",
        "ART_PUBPLAKAT",
    }


@pytest.mark.django_db
def test_collection_filter_root_is_whole_tree_but_still_scoped(corpus: None) -> None:
    """ROOT's subtree is exactly the viewer's visible rows under ROOT: a visible row in another
    tree stays out, and so do the rows under ROOT the viewer cannot see."""
    fixtures.index_beside_corpus(
        Collection(ulid="ANDERE", name="Anderer Baum", parent_id=None),
        make_article("ART_ANDERE", title="Anderswo", collection_id="ANDERE"),
    )
    page = search(VORSTAND_MEMBER, filters=SearchFilters(collection="ROOT"), page_size=200)
    assert _ulids(page) == {
        ulid for ulid, who in fixtures.EXPECTED_VISIBILITY.items() if "vorstand" in who
    }


# ===========================================================================
# Scalar / array filters.
# ===========================================================================


@pytest.mark.django_db
def test_media_type_filter(corpus: None) -> None:
    page = search(PUBLIC, filters=SearchFilters(media_type="Karte"))
    assert _ulids(page) == {"ART_PUBKARTE"}


@pytest.mark.django_db
def test_document_type_filter(corpus: None) -> None:
    page = search(PUBLIC, filters=SearchFilters(document_type="Fotografie"))
    assert _ulids(page) == {"ART_PUBFOTO", "ART_PUBLAGER"}


@pytest.mark.django_db
def test_tag_filter(corpus: None) -> None:
    page = search(PLAIN_MEMBER, filters=SearchFilters(tag="fahrten"))
    assert _ulids(page) == {"ART_PUBFOTO", "ART_PUBKARTE", "ART_MEMNOTIZ"}


@pytest.mark.django_db
def test_decade_filter(corpus: None) -> None:
    """Decade 1970 spans PUBLAGER (1972) and PUBPLAKAT (1970/.. open-ended -> includes 1970)."""
    page = search(PUBLIC, filters=SearchFilters(decade=1970))
    assert _ulids(page) == {"ART_PUBLAGER", "ART_PUBPLAKAT"}


# ===========================================================================
# Date-range filter (overlap; open-ended latest = +infinity; no date = excluded).
# ===========================================================================


@pytest.mark.django_db
def test_date_range_overlap(corpus: None) -> None:
    """1960..1969 overlaps only PUBFOTO (1965) among public docs."""
    page = search(
        PUBLIC,
        filters=SearchFilters(
            date_from=datetime.date(1960, 1, 1), date_to=datetime.date(1969, 12, 31)
        ),
    )
    assert _ulids(page) == {"ART_PUBFOTO"}


@pytest.mark.django_db
def test_date_range_includes_open_ended_article(corpus: None) -> None:
    """PUBPLAKAT is 1970/.. (open upper end): a 2020-range filter must still match it."""
    page = search(
        PUBLIC,
        filters=SearchFilters(
            date_from=datetime.date(2020, 1, 1), date_to=datetime.date(2020, 12, 31)
        ),
    )
    assert "ART_PUBPLAKAT" in _ulids(page)


@pytest.mark.django_db
def test_date_range_from_only(corpus: None) -> None:
    """date_from with no date_to: everything from 1985 on (open upper bound)."""
    page = search(PLAIN_MEMBER, filters=SearchFilters(date_from=datetime.date(1985, 1, 1)))
    # member-visible with earliest/interval reaching >= 1985: MEMNOTIZ(1988), MEMBRIEF(1990),
    # PUBPLAKAT(1970/.. open -> reaches 1985).
    assert {"ART_MEMNOTIZ", "ART_MEMBRIEF", "ART_PUBPLAKAT"} <= _ulids(page)
    assert "ART_PUBFOTO" not in _ulids(page)  # 1965, before the floor


# ===========================================================================
# Sort orders.
# ===========================================================================


@pytest.mark.django_db
def test_sort_ref_code_numeric_and_locale_aware(corpus: None) -> None:
    """de_numeric: A 1 < A 5 < A 12 (numeric, not lexicographic 'A 12' < 'A 5')."""
    page = search(PLAIN_MEMBER, sort="ref_code", page_size=200)
    akte_order = [h.ref_code for h in page.hits if h.ref_code and h.ref_code.startswith("A ")]
    assert akte_order == ["A 1", "A 5", "A 12"]


@pytest.mark.django_db
def test_sort_date_ascending_nulls_last(corpus: None) -> None:
    fixtures.index_beside_corpus(
        Collection(ulid="OHNE", name="Ohne Datum", parent_id=None),
        make_article(
            "ART_UNDATED",
            title="Undatiert",
            collection_id="OHNE",
            audience=Audience(AudienceTier.PUBLIC),
        ),
    )
    ulids = [h.ulid for h in search(PUBLIC, sort="date", page_size=200).hits]
    assert ulids[0] == "ART_PUBKARTE"  # 1958, earliest public
    assert ulids[-1] == "ART_UNDATED"


@pytest.mark.django_db
def test_equal_ranks_read_in_numeric_title_order(corpus: None) -> None:
    """A run of issues matches a search equally well; it then reads Nr. 1, 2, 10, not by ulid."""
    fixtures.index_beside_corpus(
        Collection(ulid="REIHE", name="Reihe", parent_id=None),
        *(
            make_article(
                ulid,
                title=f"Rundbrief Nr. {n}",
                collection_id="REIHE",
                audience=Audience(AudienceTier.PUBLIC),
            )
            for ulid, n in (("ART_RB_A", 10), ("ART_RB_B", 2), ("ART_RB_C", 1))
        ),
    )
    titles = [h.title for h in search(PUBLIC, text="Rundbrief").hits]
    assert titles == ["Rundbrief Nr. 1", "Rundbrief Nr. 2", "Rundbrief Nr. 10"]


# ===========================================================================
# Facets — keys, counts per viewer, exclude-own-dimension.
# ===========================================================================


@pytest.mark.django_db
def test_facet_keys_are_exactly_the_six(corpus: None) -> None:
    page = search(PUBLIC)
    assert set(page.facets.keys()) == {
        "collection",
        "media_type",
        "document_type",
        "tags",
        "decades",
        "file_kind",
    }


@pytest.mark.django_db
def test_a_facet_subset_leaves_the_rest_of_the_page_as_it_was(corpus: None) -> None:
    wanted: tuple[Facet, ...] = ("collection", "decades", "document_type")
    filters = SearchFilters(media_type="Foto")
    full = search(PUBLIC, filters=filters)
    part = search(PUBLIC, filters=filters, facets=wanted)
    assert part.facets == {key: full.facets[key] for key in wanted}
    assert (part.hits, part.total, part.dateless_count) == (
        full.hits,
        full.total,
        full.dateless_count,
    )


@pytest.mark.django_db
def test_facet_tags_via_unnest(corpus: None) -> None:
    """Array tags are unnested and counted: public 'natur' on PUBHAUS + PUBKARTE."""
    tags = _facet_map(search(PUBLIC), "tags")
    assert tags["natur"] == 2
    assert tags["lager"] == 2  # PUBFOTO, PUBLAGER


@pytest.mark.django_db
def test_facet_excludes_own_dimension(corpus: None) -> None:
    """Standard faceting: a media_type filter must NOT collapse the media_type facet — that
    facet is computed with its own filter excluded, so all media types still show."""
    filtered = search(PUBLIC, filters=SearchFilters(media_type="Foto"))
    media = _facet_map(filtered, "media_type")
    # Own dimension excluded: the facet still lists Karte/Plakat (what you could switch to),
    # each with its FULL scoped count (3 Foto, 1 Karte, 1 Plakat) — not collapsed to the selection.
    assert media == {"Foto": 3, "Karte": 1, "Plakat": 1}
    # A DIFFERENT facet DOES reflect the media_type=Foto filter: only the 3 Foto docs are counted
    # (PUBFOTO+PUBLAGER are document_type Fotografie; PUBHAUS is document_type Karte).
    doc = _facet_map(filtered, "document_type")
    assert doc == {"Fotografie": 2, "Karte": 1}


# ===========================================================================
# "Ohne Datum" facet (Part 4) — dateless count. The shared corpus dates every article, so here
# the count is 0; the tier-exclusive leak case (a restricted dateless row must not inflate a
# lesser viewer's count) needs its own corpus — see ``test_leaks_dateless.py``, mirroring the
# decade-leak module's dedicated-corpus pattern.
# ===========================================================================


@pytest.mark.django_db
def test_dateless_count_is_zero_when_every_row_is_dated(corpus: None) -> None:
    """Every corpus article has a date, so the "Ohne Datum" bucket is empty for every viewer."""
    for viewer in (PUBLIC, PLAIN_MEMBER, VORSTAND_MEMBER, ARCHIVIST):
        assert search(viewer, page_size=200).dateless_count == 0


# ===========================================================================
# Pagination.
# ===========================================================================


@pytest.mark.django_db
def test_pagination_window_and_total_stable(corpus: None) -> None:
    p1 = search(ARCHIVIST, sort="ref_code", page=1, page_size=5)
    p2 = search(ARCHIVIST, sort="ref_code", page=2, page_size=5)
    p3 = search(ARCHIVIST, sort="ref_code", page=3, page_size=5)
    assert p1.total == p2.total == p3.total == 12  # total is the full scoped count
    assert len(p1.hits) == 5
    assert len(p2.hits) == 5
    assert len(p3.hits) == 2  # 12 = 5 + 5 + 2
    # No overlap across windows.
    assert _ulids(p1) & _ulids(p2) == set()
    assert _ulids(p1) | _ulids(p2) | _ulids(p3) == _ulids(search(ARCHIVIST, page_size=200))


@pytest.mark.django_db
def test_pagination_past_end_is_empty(corpus: None) -> None:
    page = search(PUBLIC, page=99, page_size=50)
    assert page.hits == ()
    assert page.total == 5


@pytest.mark.django_db
def test_page_size_is_capped(corpus: None) -> None:
    """An absurd page_size is capped at the maximum, not honored verbatim."""
    fixtures.index_beside_corpus(
        Collection(ulid="VIELE", name="Viele", parent_id=None),
        *(
            Article(ulid=f"ART_VIELE_{n:03}", title="Viele", collection_id="VIELE")
            for n in range(_MAX_PAGE_SIZE + 1)
        ),
    )
    page = search(ARCHIVIST, page_size=100_000)
    assert page.total > _MAX_PAGE_SIZE
    assert len(page.hits) == _MAX_PAGE_SIZE


# ===========================================================================
# Empty-text browse.
# ===========================================================================


@pytest.mark.django_db
def test_empty_text_browse_is_in_ulid_order(corpus: None) -> None:
    """A browse has no rank, so it orders by ulid — whatever order the rows were indexed in."""
    fixtures.index_beside_corpus(
        Collection(ulid="SPAET", name="Spät indexiert", parent_id=None),
        make_article("ART_0B", title="Zweiter", collection_id="SPAET"),
        make_article("ART_0A", title="Erster", collection_id="SPAET"),
    )
    ulids = [h.ulid for h in search(PLAIN_MEMBER, page_size=200).hits]
    assert ulids == sorted(ulids)
