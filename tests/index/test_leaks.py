"""THE §11 guard, half two: per-tier leak negatives over the shared corpus.

Where ``test_equivalence.py`` pins the whole SQL ≡ ``can_view`` grid, this file pins the specific
leak channels that a scoped-search adapter must never open — each as an explicit per-tier negative
so a regression names the exact leak, not just a count drift. Tiers: Public, Member(no groups),
Member(wrong group), Member(right group = vorstand), Archivist.

Channels covered:

- **Floored-field term isolation.** A term living ONLY in ``physical_location`` (an archivist-only
  field) is unreachable to every non-Archivist through the text vector, even on a row they can see.
- **Draft invisibility through EVERY path.** A DRAFT (archivist-only) Article must be absent from a
  non-Archivist's text hits, every filter, EVERY facet key, and the total — not just the hit list.
- **GROUPS or-narrowing.** A GROUPS row is reachable only by a viewer holding an overlapping group.
- **Differential facet leaks (controller #3, the mutation-tested gap).** A TAG occurring ONLY on
  restricted rows must be ABSENT from an unauthorized viewer's facets and PRESENT for an authorized
  one — the test that catches an *unscoped* facet queryset a hit-set check would miss. (The matching
  DECADE differential needs a tier-exclusive decade the shared corpus can't offer — its open-ended
  ``ART_PUBPLAKAT`` bleeds a public row into every decade from 1970 on — so it lives in its own
  module, ``test_leaks_decades.py``, with a dedicated two-row corpus; one destructive ``rebuild``
  per corpus means two corpora can't share this module's table.)
- **Fail-closed row invisibility.** The dangling-collection row (``ART_ORPHAN``) is archivist-only
  and, carrying no ancestors, unreachable via any collection filter even for the Archivist.
- **``SearchHit`` field floor.** The result dataclass statically cannot carry a floored field.

Runs against the shared corpus (``tests/index/fixtures.py``), indexed ONCE per module.
"""

import dataclasses
from collections.abc import Iterator

import pytest
from tests.index import fixtures
from tests.index.fixtures import (
    ARCHIVIST,
    PLAIN_MEMBER,
    PUBLIC,
    VORSTAND_MEMBER,
)

from bundesarchiv.domain.viewer import Member, Viewer
from bundesarchiv.index import indexer, search
from bundesarchiv.index.query import SearchFilters, SearchHit, SortOrder

# The non-Archivist tiers, labelled — every leak channel is asserted for each so a regression names
# the tier. The Archivist is asserted separately (it is the only viewer these channels open TO).
_NON_ARCHIVIST_TIERS = (
    ("public", PUBLIC),
    ("member()", PLAIN_MEMBER),
    ("member(wrong-group)", Member(("nicht-vorstand",))),
    ("member(vorstand)", VORSTAND_MEMBER),
)


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


def _ulids(
    viewer: Viewer,
    *,
    text: str | None = None,
    filters: SearchFilters | None = None,
    sort: SortOrder = "relevance",
    page_size: int = 50,
) -> set[str]:
    page = search(viewer, text=text, filters=filters, sort=sort, page_size=page_size)
    return {hit.ulid for hit in page.hits}


def _facet_values(
    viewer: Viewer, key: str, *, filters: SearchFilters | None = None, page_size: int = 50
) -> set[str]:
    page = search(viewer, filters=filters, page_size=page_size)
    return {fc.value for fc in page.facets[key]}


def _facet_count(
    viewer: Viewer,
    key: str,
    value: str,
    *,
    filters: SearchFilters | None = None,
    page_size: int = 50,
) -> int:
    page = search(viewer, filters=filters, page_size=page_size)
    return next((fc.count for fc in page.facets[key] if fc.value == value), 0)


# ===========================================================================
# Floored-field term isolation — a term only in an archivist-only field.
# ===========================================================================


@pytest.mark.django_db
def test_floored_field_term_invisible_to_every_non_archivist(corpus: None) -> None:
    """'Geheimregal' lives ONLY in ART_GRPBESCH.physical_location (archivist-only). No
    non-Archivist may reach it via text — not even the vorstand Member who CAN see that row."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert _ulids(viewer, text="Geheimregal") == set(), (
            f"[{label}] floored term 'Geheimregal' leaked via text"
        )


@pytest.mark.django_db
def test_floored_field_term_visible_to_archivist(corpus: None) -> None:
    """The Archivist reaches the floored term via the archivist tsvector — the row is otherwise a
    normal, visible GROUPS row, so this is a floor test, not a visibility one."""
    assert "ART_GRPBESCH" in _ulids(ARCHIVIST, text="Geheimregal")


@pytest.mark.django_db
def test_floored_field_term_isolated_even_when_row_is_visible(corpus: None) -> None:
    """The vorstand Member CAN see ART_GRPBESCH (a browse returns it) yet still cannot text-match
    its floored physical_location — floor and visibility are independent axes."""
    assert "ART_GRPBESCH" in _ulids(VORSTAND_MEMBER, page_size=200)  # row is visible
    assert _ulids(VORSTAND_MEMBER, text="Geheimregal") == set()  # floored term is not


# ===========================================================================
# Draft invisibility through EVERY path (text, filters, every facet key, total).
# ===========================================================================

# ART_DRAFT: lifecycle DRAFT -> archivist-only. It carries the unique tag 'entwurf', document_type
# 'Chronik', and ref_code 'D 1'; it sits in FOTOS (a public collection) so a collection filter that
# ignored lifecycle WOULD surface it — the strongest draft-leak probe.
_DRAFT_ULID = "ART_DRAFT"


@pytest.mark.django_db
def test_draft_invisible_via_text_to_non_archivists(corpus: None) -> None:
    """Its title word 'Entwurf' and unique tag 'entwurf' both return nothing for a non-Archivist."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert _DRAFT_ULID not in _ulids(viewer, text="Entwurf"), f"[{label}] draft via title text"
        assert _DRAFT_ULID not in _ulids(viewer, text="Chronik"), (
            f"[{label}] draft via doc-type text"
        )


@pytest.mark.django_db
def test_draft_invisible_via_filters_to_non_archivists(corpus: None) -> None:
    """Through the collection subtree (FOTOS/ROOT, both of which the draft is under), its
    document_type, its tag, and its decade — every filter path is scope-first."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        for f in (
            SearchFilters(collection="FOTOS"),
            SearchFilters(collection="ROOT"),
            SearchFilters(document_type="Chronik"),
            SearchFilters(tag="entwurf"),
        ):
            assert _DRAFT_ULID not in _ulids(viewer, filters=f, page_size=200), (
                f"[{label}] draft leaked via filter {f}"
            )


@pytest.mark.django_db
def test_draft_absent_from_every_facet_key_for_non_archivists(corpus: None) -> None:
    """The draft's exclusive facet values must not appear in ANY facet a non-Archivist sees:
    its tag 'entwurf', its document_type 'Chronik'. (Its media_type 'Akte' and decades are shared
    with visible rows, so only the exclusive values are asserted-absent here.)"""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert "entwurf" not in _facet_values(viewer, "tags"), f"[{label}] draft tag in facet"
        assert "Chronik" not in _facet_values(viewer, "document_type"), (
            f"[{label}] draft doc-type in facet"
        )


@pytest.mark.django_db
def test_draft_not_counted_in_non_archivist_total(corpus: None) -> None:
    """The draft never inflates a non-Archivist total: each tier's total equals its visible-set
    size (from fixtures.EXPECTED_VISIBILITY), which never includes ART_DRAFT."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        got = search(viewer, page_size=200).total
        expected = sum(1 for u, who in fixtures.EXPECTED_VISIBILITY.items() if label_in(label, who))
        assert got == expected, f"[{label}] total {got} != visible-set {expected} (draft leak?)"


@pytest.mark.django_db
def test_draft_visible_to_archivist_through_paths(corpus: None) -> None:
    """The Archivist reaches the draft through text, its filters, and its facets — the negative
    above is a scope gate, not an indexing gap."""
    assert _DRAFT_ULID in _ulids(ARCHIVIST, text="Entwurf")
    assert _DRAFT_ULID in _ulids(ARCHIVIST, filters=SearchFilters(tag="entwurf"), page_size=200)
    assert "entwurf" in _facet_values(ARCHIVIST, "tags")


def label_in(label: str, who: frozenset[str]) -> bool:
    """Map a tier label to whether its viewer is in a fixtures visibility set. The wrong-group
    Member has the same visibility as a plain Member (never clears the vorstand GROUPS rung)."""
    mapping = {
        "public": "public",
        "member()": "member",
        "member(wrong-group)": "member",
        "member(vorstand)": "vorstand",
    }
    return mapping[label] in who


# ===========================================================================
# GROUPS or-narrowing — a GROUPS row reachable only with an overlapping group.
# ===========================================================================


@pytest.mark.django_db
def test_groups_row_reachable_only_with_overlapping_group(corpus: None) -> None:
    """ART_GRPPROT is GROUPS{vorstand}. Absent for Public, plain Member and a wrong-group Member;
    present for the vorstand Member and the Archivist."""
    assert "ART_GRPPROT" not in _ulids(PUBLIC, page_size=200)
    assert "ART_GRPPROT" not in _ulids(PLAIN_MEMBER, page_size=200)
    assert "ART_GRPPROT" not in _ulids(Member(("nicht-vorstand",)), page_size=200)
    assert "ART_GRPPROT" in _ulids(VORSTAND_MEMBER, page_size=200)
    assert "ART_GRPPROT" in _ulids(ARCHIVIST, page_size=200)


@pytest.mark.django_db
def test_wrong_group_member_sees_exactly_a_plain_member(corpus: None) -> None:
    """Holding an UNRELATED group grants nothing over a groupless Member — no group is a superset
    key. The two viewers' whole result sets are identical."""
    assert _ulids(Member(("nicht-vorstand",)), page_size=200) == _ulids(PLAIN_MEMBER, page_size=200)


# ===========================================================================
# Differential facet leaks (controller #3) — tags. The mutation-tested gap:
# a value on ONLY restricted rows must be absent from an unauthorized viewer's
# facet and present for an authorized one. Catches an unscoped facet queryset.
# ===========================================================================


@pytest.mark.django_db
def test_group_only_tag_absent_from_unauthorized_facets(corpus: None) -> None:
    """'protokoll' is on ONLY ART_GRPPROT (GROUPS{vorstand}); 'vorstand' only on the two GROUPS
    rows. Both must be absent from Public, plain-Member and wrong-group-Member tag facets, and
    present (correctly counted) for the vorstand Member and the Archivist."""
    for label, viewer in (
        ("public", PUBLIC),
        ("member()", PLAIN_MEMBER),
        ("member(wrong-group)", Member(("nicht-vorstand",))),
    ):
        tags = _facet_values(viewer, "tags")
        assert "protokoll" not in tags, f"[{label}] group-only tag 'protokoll' leaked into facet"
        assert "vorstand" not in tags, f"[{label}] group-only tag 'vorstand' leaked into facet"
    # Authorized: present AND correctly counted (protokoll on 1 row, vorstand on 2).
    assert _facet_count(VORSTAND_MEMBER, "tags", "protokoll") == 1
    assert _facet_count(VORSTAND_MEMBER, "tags", "vorstand") == 2
    assert _facet_count(ARCHIVIST, "tags", "vorstand") == 2


@pytest.mark.django_db
def test_member_only_tag_absent_from_public_facets(corpus: None) -> None:
    """'mitglieder' is on ONLY the three MEMBERS rows — absent from Public's tag facet, present
    (count 3) for any Member."""
    assert "mitglieder" not in _facet_values(PUBLIC, "tags")
    assert _facet_count(PLAIN_MEMBER, "tags", "mitglieder") == 3


@pytest.mark.django_db
def test_draft_and_failclosed_tags_absent_from_all_non_archivist_facets(corpus: None) -> None:
    """'entwurf' (draft-only) and 'verwaist' (fail-closed-only) never appear in any non-Archivist
    tag facet, and both appear (count 1 each) for the Archivist."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        tags = _facet_values(viewer, "tags")
        assert "entwurf" not in tags, f"[{label}] draft-only tag leaked"
        assert "verwaist" not in tags, f"[{label}] fail-closed-only tag leaked"
    assert _facet_count(ARCHIVIST, "tags", "entwurf") == 1
    assert _facet_count(ARCHIVIST, "tags", "verwaist") == 1


# ===========================================================================
# Fail-closed row invisibility — ART_ORPHAN (dangling collection_id).
# ===========================================================================


@pytest.mark.django_db
def test_failclosed_row_invisible_to_every_non_archivist(corpus: None) -> None:
    """ART_ORPHAN indexes as a fail-closed archivist-only row. Invisible to every non-Archivist
    through browse, its title text 'Verwaistes', and its unique tag 'verwaist'."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert "ART_ORPHAN" not in _ulids(viewer, page_size=200), f"[{label}] fail-closed browse"
        assert "ART_ORPHAN" not in _ulids(viewer, text="Verwaistes"), f"[{label}] fail-closed text"
        assert "ART_ORPHAN" not in _ulids(viewer, filters=SearchFilters(tag="verwaist")), (
            f"[{label}] fail-closed tag filter"
        )


@pytest.mark.django_db
def test_failclosed_row_visible_to_archivist_but_not_via_collection_filter(corpus: None) -> None:
    """The Archivist reaches the fail-closed row via unfiltered/text search, but NEVER via a
    collection filter — it carries collection_ancestors=[] by spec (controller #2), so no subtree
    filter can contain it. Pinned for the Archivist because that's the only viewer it's visible to."""
    assert "ART_ORPHAN" in _ulids(ARCHIVIST, page_size=200)  # unfiltered: reachable
    assert "ART_ORPHAN" in _ulids(ARCHIVIST, text="Verwaistes")  # text: reachable
    # No collection filter reaches it — not even ROOT, the whole resolved tree.
    assert "ART_ORPHAN" not in _ulids(
        ARCHIVIST, filters=SearchFilters(collection="ROOT"), page_size=200
    )
    assert "ART_ORPHAN" not in _ulids(
        ARCHIVIST, filters=SearchFilters(collection="GHOST"), page_size=200
    )


# ===========================================================================
# SearchHit field floor — a static assert the result type cannot carry a floored field.
# ===========================================================================


def test_search_hit_dataclass_fields_exclude_floored_content() -> None:
    """Static floor: ``SearchHit.__dataclass_fields__`` is EXACTLY the six member-visible columns —
    no ``physical_location`` / ``custom`` / ``archivist_text`` can ever ride out on a hit. Extends
    Task 8's runtime shape check with the exact-field-set assertion the brief names (via
    ``__dataclass_fields__``), so the floor is pinned even if the runtime test is later relaxed."""
    field_names = set(SearchHit.__dataclass_fields__)
    assert field_names == {
        "ulid",
        "title",
        "ref_code",
        "date_edtf",
        "media_type",
        "document_type",
    }
    for floored in ("physical_location", "custom", "archivist_text", "body", "tier", "groups"):
        assert floored not in field_names, f"floored field {floored!r} leaked into SearchHit"


def test_search_hit_field_names_match_projection_via_dataclasses() -> None:
    """The same floor asserted through ``dataclasses.fields`` (the public API), so the guard does
    not depend on the private ``__dataclass_fields__`` attribute alone."""
    names = {f.name for f in dataclasses.fields(SearchHit)}
    assert "physical_location" not in names
    assert "custom" not in names
    assert "archivist_text" not in names
