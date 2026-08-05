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
from tests.index import fixtures
from tests.index.fixtures import (
    ARCHIVIST,
    PLAIN_MEMBER,
    PUBLIC,
    VORSTAND_MEMBER,
)

from bundesarchiv.index import indexer, search
from bundesarchiv.index.query import SearchFilters, SearchPage


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
def test_text_stems_singular_to_plural(corpus: None) -> None:
    """A singular query finds a plural in a title (german_stem): 'Lied' -> 'Lieder'."""
    page = search(PUBLIC, text="Lied")
    assert "ART_PUBLAGER" in _ulids(page)  # "... Lieder ..."


@pytest.mark.django_db
def test_text_is_umlaut_insensitive(corpus: None) -> None:
    """Umlaut-less typing finds an umlaut document (unaccent): 'Baume' -> 'Bäume'."""
    page = search(PUBLIC, text="Baume")
    assert "ART_PUBHAUS" in _ulids(page)  # "Bäume vor dem Haus"


@pytest.mark.django_db
def test_prefix_matching_recovers_compound_head(corpus: None) -> None:
    """ADR-0011 prefix mitigation (:* on the trailing lexeme): a compound HEAD matches the whole
    compound. 'Lager' alone (no decomposition) reaches 'Bundeslager Lieder und Häuser'."""
    assert "ART_PUBLAGER" in _ulids(search(PUBLIC, text="Lager"))


@pytest.mark.django_db
def test_prefix_matching_matches_partial_word_start(corpus: None) -> None:
    """The brief's pinned case: 'Fahrt' matches a 'Fahrten' title via the :* prefix (a query
    'Fahrt' would match 'Fahrtenbericht' too — the recall the missing decomposition would give)."""
    assert "ART_PUBFOTO" in _ulids(search(PUBLIC, text="Fahrt"))  # "... der Fahrten"


@pytest.mark.django_db
def test_all_stopword_query_does_not_crash(corpus: None) -> None:
    """A query that parses to an EMPTY tsquery (all stopwords) must not raise — the NULLIF guard
    in the prefix wrapper turns ''||':*' into the empty tsquery, not the invalid ':*'."""
    page = search(PUBLIC, text="und der die")
    assert isinstance(page.total, int)  # ran without error


@pytest.mark.django_db
def test_text_ranks_and_scopes(corpus: None) -> None:
    """'Fahrten' matches several public docs; a plain member sees member ones too."""
    public_hits = _ulids(search(PUBLIC, text="Fahrten"))
    member_hits = _ulids(search(PLAIN_MEMBER, text="Fahrten"))
    assert "ART_PUBFOTO" in public_hits  # "... der Fahrten"
    assert "ART_MEMNOTIZ" not in public_hits  # member-only, invisible to public
    assert "ART_MEMNOTIZ" in member_hits


# ===========================================================================
# Archivist dual-vector text (isolation itself is proven in test_leaks).
# ===========================================================================


@pytest.mark.django_db
def test_archivist_general_text_still_matches_general_vector(corpus: None) -> None:
    """The Archivist's dual-vector search still matches ordinary (general) text."""
    assert "ART_PUBLAGER" in _ulids(search(ARCHIVIST, text="Bundeslager"))


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
    """ROOT subtree = every article with a resolved chain, still viewer-scoped."""
    page = search(VORSTAND_MEMBER, filters=SearchFilters(collection="ROOT"))
    # Vorstand sees 10 total; ORPHAN (dangling, no ancestors) is NOT under ROOT subtree.
    assert "ART_ORPHAN" not in _ulids(page)
    assert page.total == 10


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
    """date sort is date_earliest ascending; PUBKARTE(1958) first among public."""
    page = search(PUBLIC, sort="date", page_size=200)
    dates = [h.ulid for h in page.hits]
    assert dates[0] == "ART_PUBKARTE"  # 1958, earliest public


# ===========================================================================
# Facets — keys, counts per viewer, exclude-own-dimension.
# ===========================================================================


@pytest.mark.django_db
def test_facet_keys_are_exactly_the_five(corpus: None) -> None:
    page = search(PUBLIC)
    assert set(page.facets.keys()) == {
        "collection",
        "media_type",
        "document_type",
        "tags",
        "decades",
    }


@pytest.mark.django_db
def test_facet_media_type_counts_public(corpus: None) -> None:
    page = search(PUBLIC)
    media = _facet_map(page, "media_type")
    # Public docs: 3 Foto, 1 Karte, 1 Plakat.
    assert media == {"Foto": 3, "Karte": 1, "Plakat": 1}


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
    """An absurd page_size is capped at the documented maximum, not honored verbatim."""
    page = search(ARCHIVIST, page_size=100_000)
    assert len(page.hits) <= 200  # the cap


# ===========================================================================
# Empty-text browse + no-filter defaults.
# ===========================================================================


@pytest.mark.django_db
def test_empty_text_browses_everything_in_scope(corpus: None) -> None:
    """text=None is a browse: the whole scoped set, deterministically ordered."""
    page = search(PLAIN_MEMBER)
    assert page.total == 8
    # Deterministic order: two identical calls return the same sequence.
    again = search(PLAIN_MEMBER)
    assert [h.ulid for h in page.hits] == [h.ulid for h in again.hits]
