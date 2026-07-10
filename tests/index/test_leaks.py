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


def _hits(viewer: Viewer, *, page_size: int = 200) -> tuple[SearchHit, ...]:
    return search(viewer, page_size=page_size).hits


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
# Media captions (ADR 0015) — searchable at body weight, but STILL scope-first.
# A caption on a restricted row must never open a leak the row itself doesn't.
# ===========================================================================


@pytest.mark.django_db
def test_public_caption_word_reaches_every_tier(corpus: None) -> None:
    """'Zeltwiese' lives ONLY in ART_PUBFOTO's media caption (a public, published row). Because it
    joins the body-weight FTS bucket, every tier — including the Archivist — reaches the row by that
    caption word. This is the positive that proves captions actually index (the negatives below are
    scope gates, not an indexing gap)."""
    for label, viewer in (*_NON_ARCHIVIST_TIERS, ("archivist", ARCHIVIST)):
        assert "ART_PUBFOTO" in _ulids(viewer, text="Zeltwiese"), (
            f"[{label}] public caption word did not reach a tier that can see the row"
        )


@pytest.mark.django_db
def test_group_caption_word_does_not_leak_to_unauthorized_tiers(corpus: None) -> None:
    """'Tresornotiz' is ONLY in ART_GRPPROT's caption (GROUPS{vorstand}). A caption is member-
    visible content, so it is scope-first like body text: absent for Public, plain Member and a
    wrong-group Member; present for the vorstand Member and the Archivist."""
    assert _ulids(PUBLIC, text="Tresornotiz") == set()
    assert _ulids(PLAIN_MEMBER, text="Tresornotiz") == set()
    assert _ulids(Member(("nicht-vorstand",)), text="Tresornotiz") == set()
    assert "ART_GRPPROT" in _ulids(VORSTAND_MEMBER, text="Tresornotiz")
    assert "ART_GRPPROT" in _ulids(ARCHIVIST, text="Tresornotiz")


@pytest.mark.django_db
def test_draft_caption_word_invisible_to_every_non_archivist(corpus: None) -> None:
    """'Skizzenblatt' is ONLY in ART_DRAFT's caption. A draft is archivist-only regardless of
    audience, so its caption word yields ZERO hits for every non-Archivist tier and reaches only
    the Archivist — the caption channel does not bypass the lifecycle gate."""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert _ulids(viewer, text="Skizzenblatt") == set(), (
            f"[{label}] draft caption word 'Skizzenblatt' leaked via the caption channel"
        )
    assert "ART_DRAFT" in _ulids(ARCHIVIST, text="Skizzenblatt")


# ===========================================================================
# SearchHit scope data (is_draft / tier / groups) — archivist chrome, no cross-tier leak.
# These fields ride on returned hits so the ledger can render SICHTBARKEIT + ENTWURF; the guarantee
# is that _viewer_scope already restricts WHICH rows come back, so the data on them is never a leak.
# ===========================================================================


@pytest.mark.django_db
def test_no_non_archivist_hit_is_ever_a_draft(corpus: None) -> None:
    """A non-archivist never receives an archivist_only row, so no hit they get is_draft. (The
    draft ART_DRAFT is absent from their results entirely — this pins the FIELD too: even if a bug
    returned it, is_draft would have to be False on every row a non-archivist can see.)"""
    for label, viewer in _NON_ARCHIVIST_TIERS:
        assert all(not hit.is_draft for hit in _hits(viewer)), f"[{label}] a draft rode a hit"


@pytest.mark.django_db
def test_archivist_hits_mark_the_draft(corpus: None) -> None:
    """The archivist DOES get is_draft=True on the draft row (the chrome needs it) and False on
    published rows — draft-vs-published is honestly carried."""
    by_ulid = {hit.ulid: hit for hit in _hits(ARCHIVIST)}
    assert by_ulid["ART_DRAFT"].is_draft is True
    assert by_ulid["ART_PUBFOTO"].is_draft is False


@pytest.mark.django_db
def test_failclosed_hit_is_not_marked_draft_for_archivist(corpus: None) -> None:
    """A fail-closed row (broken chain, archivist_only) is NOT a draft — the ENTWURF badge must
    never mislabel it. Only the archivist sees it at all."""
    by_ulid = {hit.ulid: hit for hit in _hits(ARCHIVIST)}
    assert by_ulid["ART_ORPHAN"].is_draft is False


@pytest.mark.django_db
def test_group_names_on_a_members_hits_are_only_groups_they_hold(corpus: None) -> None:
    """The cross-tier leak the reviewer will probe: a GROUPS row's ``groups`` may ride out ONLY to a
    viewer who holds one of them (that's why _viewer_scope returned the row). The vorstand member
    sees ART_GRPPROT/ART_GRPBESCH carrying ('vorstand', ...) — groups they hold; a plain member and
    a wrong-group member receive NO GROUPS row at all, so no group name can ride to them."""
    vorstand_hits = {h.ulid: h for h in _hits(VORSTAND_MEMBER)}
    assert "vorstand" in vorstand_hits["ART_GRPPROT"].groups  # a group the viewer holds
    # Every GROUPS-tier hit this member gets overlaps the groups they hold — never a foreign name.
    held = {"vorstand"}
    for hit in vorstand_hits.values():
        if hit.tier == "GROUPS":
            assert held & set(hit.groups), (
                f"{hit.ulid}: group names the viewer does not hold rode out"
            )
    # Plain + wrong-group members: no GROUPS row reaches them, so groups never carry a foreign name.
    for label, viewer in (
        ("member()", PLAIN_MEMBER),
        ("member(wrong)", Member(("nicht-vorstand",))),
    ):
        for hit in _hits(viewer):
            assert hit.tier != "GROUPS", f"[{label}] a GROUPS row leaked to a non-holder"


@pytest.mark.django_db
def test_public_hits_carry_only_public_tier_no_groups(corpus: None) -> None:
    """Public only ever gets PUBLIC-tier, non-draft, groupless hits — the scope data is trivially
    leak-free for the public tier."""
    for hit in _hits(PUBLIC):
        assert hit.tier == "PUBLIC"
        assert hit.groups == ()
        assert hit.is_draft is False


# ===========================================================================
# SearchHit field floor — a static assert the result type cannot carry a floored field.
# ===========================================================================


def test_search_hit_dataclass_fields_exclude_floored_content() -> None:
    """Static floor: ``SearchHit.__dataclass_fields__`` is EXACTLY the member-visible identity/
    metadata columns PLUS the archivist-chrome scope data (is_draft/tier/groups) — and NEVER a
    floored field. DELIBERATELY extended (4.6 render path): is_draft/tier/groups were added so the
    ledger's SICHTBARKEIT column + ENTWURF badge render from structured data; they carry no
    cross-tier leak by construction (see SearchHit docstring) and the template gates them to the
    archivist. The floored fields below stay OUT — this is a conscious widening, not a relaxation."""
    field_names = set(SearchHit.__dataclass_fields__)
    assert field_names == {
        "ulid",
        "title",
        "ref_code",
        "date_edtf",
        "media_type",
        "document_type",
        "is_draft",
        "tier",
        "groups",
    }
    for floored in (
        "physical_location",
        "custom",
        "archivist_text",
        "body",
        "caption",  # captions feed FTS only (ADR 0015); never a result field
        "media",
    ):
        assert floored not in field_names, f"floored field {floored!r} leaked into SearchHit"


def test_search_hit_field_names_match_projection_via_dataclasses() -> None:
    """The same floor asserted through ``dataclasses.fields`` (the public API), so the guard does
    not depend on the private ``__dataclass_fields__`` attribute alone."""
    names = {f.name for f in dataclasses.fields(SearchHit)}
    assert "physical_location" not in names
    assert "custom" not in names
    assert "archivist_text" not in names
