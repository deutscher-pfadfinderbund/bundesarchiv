"""Viewer-facing access predicate — `can_view` composes effective_audience + Viewer.

Fail-closed (ADR 0001): a non-Published Article is Archivist-only; a chain resolved for a
different Article denies everyone. Fixture-driven, no IO. Chains are `ResolvedChain`s.
"""

from dataclasses import fields

import pytest

from bundesarchiv.domain.access import ARCHIVIST_ONLY_FIELDS, can_view, preview, project
from bundesarchiv.domain.collections import ResolvedChain
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


def _article(
    *,
    audience: Audience | None = None,
    lifecycle: Lifecycle = Lifecycle.PUBLISHED,
    collection_id: str = "c-leaf",
) -> Article:
    return Article(
        ulid="01J0",
        title="Zeltlager 1955",
        collection_id=collection_id,
        lifecycle=lifecycle,
        audience=audience,
    )


def _chain(collection_id: str = "c-leaf") -> ResolvedChain:
    # A single root Collection that owns the Article — a minimal valid resolved chain.
    return ResolvedChain((Collection(ulid=collection_id, name=collection_id),))


def test_public_viewer_sees_a_published_public_article() -> None:
    article = _article(audience=Audience(AudienceTier.PUBLIC))
    assert can_view(Public(), article, _chain()) is True


def test_public_viewer_cannot_see_a_members_article() -> None:
    article = _article(audience=Audience(AudienceTier.MEMBERS))
    assert can_view(Public(), article, _chain()) is False


def test_member_sees_members_and_public_articles() -> None:
    assert can_view(Member(), _article(audience=Audience(AudienceTier.MEMBERS)), _chain()) is True
    assert can_view(Member(), _article(audience=Audience(AudienceTier.PUBLIC)), _chain()) is True


def test_archivist_sees_a_members_article() -> None:
    article = _article(audience=Audience(AudienceTier.MEMBERS))
    assert can_view(Archivist(), article, _chain()) is True


def test_a_draft_is_archivist_only_regardless_of_viewer() -> None:
    # The Lifecycle gate (via effective_audience -> ArchivistOnly) denies everyone but Archivist.
    draft = _article(audience=Audience(AudienceTier.PUBLIC), lifecycle=Lifecycle.DRAFT)
    assert can_view(Public(), draft, _chain()) is False
    assert can_view(Member(), draft, _chain()) is False
    assert can_view(Archivist(), draft, _chain()) is True


def _groups_article() -> Article:
    return _article(audience=Audience(AudienceTier.GROUPS, ("vorstand", "stamm-koeln")))


def test_member_in_one_of_the_named_groups_can_view() -> None:
    # OR-combination: holding any single named group qualifies.
    assert can_view(Member(("stamm-koeln",)), _groups_article(), _chain()) is True


def test_member_in_none_of_the_named_groups_cannot_view() -> None:
    assert can_view(Member(("stamm-bonn",)), _groups_article(), _chain()) is False


def test_member_with_no_groups_cannot_view_a_groups_article() -> None:
    # The zero-groups edge: the OR over no held groups is vacuously False — fail closed.
    assert can_view(Member(), _groups_article(), _chain()) is False


def test_archivist_always_views_a_groups_article() -> None:
    assert can_view(Archivist(), _groups_article(), _chain()) is True


def test_public_cannot_view_a_groups_article() -> None:
    assert can_view(Public(), _groups_article(), _chain()) is False


def _inherited_groups_chain() -> ResolvedChain:
    # A silent leaf under a root that carries the GROUPS rung — the rung is INHERITED.
    return ResolvedChain(
        (
            Collection(ulid="c-leaf", name="c-leaf", parent_id="c-root"),
            Collection(
                ulid="c-root",
                name="c-root",
                audience=Audience(AudienceTier.GROUPS, ("vorstand", "stamm-koeln")),
            ),
        )
    )


def test_can_view_narrows_a_member_against_an_inherited_groups_rung() -> None:
    # The leak surface: can_view must honor the RESOLVER's output (the inherited rung), not
    # just the Article's own audience. A regression consulting article.audience would expose it.
    article = _article(audience=None, collection_id="c-leaf")
    chain = _inherited_groups_chain()
    assert can_view(Member(("vorstand",)), article, chain) is True
    assert can_view(Member(("stamm-bonn",)), article, chain) is False
    assert can_view(Public(), article, chain) is False


def test_member_holding_several_groups_clears_a_rung_naming_only_one() -> None:
    # OR over the FULL held set (not first-element, not AND): rung names vorstand+stamm-koeln,
    # the Member holds three groups and only stamm-koeln matches -> True.
    held = Member(("stamm-bonn", "stamm-koeln", "andere"))
    assert can_view(held, _groups_article(), _chain()) is True


def test_member_holding_several_unnamed_groups_cannot_view() -> None:
    held = Member(("stamm-bonn", "andere"))
    assert can_view(held, _groups_article(), _chain()) is False


def test_preview_surfaces_inherited_group_names() -> None:
    # preview must surface the group names of an INHERITED GROUPS rung, not only an explicit one.
    article = _article(audience=None, collection_id="c-leaf", lifecycle=Lifecycle.DRAFT)
    p = preview(article, _inherited_groups_chain())
    assert p.public is False
    assert p.members is False
    assert p.groups == ("vorstand", "stamm-koeln")
    assert p.visible_fields != frozenset()  # group members still see the non-floored fields


def test_can_view_denies_everyone_on_a_chain_resolved_for_a_different_article() -> None:
    # The chain is a valid ResolvedChain but its leaf is not this Article's Collection — a
    # wiring bug. can_view catches the MisresolvedChain and denies (not raises). (An *empty*
    # chain can no longer reach here at all — ResolvedChain(()) fails at construction.)
    article = _article(collection_id="c-leaf", audience=Audience(AudienceTier.PUBLIC))
    wrong_chain = ResolvedChain((Collection(ulid="c-other", name="c-other"),))
    assert can_view(Public(), article, wrong_chain) is False
    assert can_view(Archivist(), article, wrong_chain) is False


def _physical_article() -> Article:
    return Article(
        ulid="01J0",
        title="Zeltlager 1955",
        collection_id="c-leaf",
        lifecycle=Lifecycle.PUBLISHED,
        audience=Audience(AudienceTier.PUBLIC),
        ref_code="Foto-1955/007",
        physical_location="Magazin 2 / Regal B / Mappe 14",
        custom=(("herkunft", "Familie Müller"),),
    )


def test_project_floors_archivist_only_fields_for_a_member() -> None:
    projected = project(Member(), _physical_article())
    assert projected.physical_location is None
    assert projected.custom == ()


def test_project_floors_archivist_only_fields_for_public() -> None:
    projected = project(Public(), _physical_article())
    assert projected.physical_location is None
    assert projected.custom == ()


def test_project_is_unchanged_for_an_archivist() -> None:
    article = _physical_article()
    assert project(Archivist(), article) == article  # an Archivist sees everything


def test_project_preserves_non_floored_fields_for_a_member() -> None:
    article = _physical_article()
    projected = project(Member(), article)
    assert projected.title == article.title
    assert projected.ref_code == article.ref_code
    assert projected.audience == article.audience
    assert projected.lifecycle == article.lifecycle


def test_project_does_not_mutate_the_source_article() -> None:
    article = _physical_article()
    project(Member(), article)
    assert article.physical_location is not None  # the frozen source is untouched


def test_project_floors_exactly_the_declared_archivist_only_fields() -> None:
    # Drift guard: floor exactly ARCHIVIST_ONLY_FIELDS — no more (over-flooring a public field),
    # no less (a leak if a field is added to the set but not to project's explicit kwargs).
    article = _physical_article()
    projected = project(Member(), article)
    differing = {
        f.name for f in fields(article) if getattr(article, f.name) != getattr(projected, f.name)
    }
    assert differing == ARCHIVIST_ONLY_FIELDS


def test_preview_shows_post_publish_audience_for_a_draft() -> None:
    # "If published now" (ADR 0001): the Lifecycle gate is bypassed, so a Public Draft previews
    # as world-visible — the warning an Archivist needs *before* publishing.
    draft = _article(audience=Audience(AudienceTier.PUBLIC), lifecycle=Lifecycle.DRAFT)
    p = preview(draft, _chain())
    assert p.public is True
    assert p.members is True


def test_preview_agrees_with_can_view_for_a_published_article() -> None:
    article = _article(audience=Audience(AudienceTier.MEMBERS))
    p = preview(article, _chain())
    assert p.public == can_view(Public(), article, _chain())
    assert p.members == can_view(Member(), article, _chain())


def test_preview_surfaces_the_named_groups_for_a_groups_article() -> None:
    p = preview(_groups_article(), _chain())
    assert p.public is False
    assert p.members is False
    assert p.groups == ("vorstand", "stamm-koeln")


def test_preview_visible_fields_exclude_the_archivist_only_fields() -> None:
    p = preview(_physical_article(), _chain())
    assert p.visible_fields == {f.name for f in fields(Article)} - ARCHIVIST_ONLY_FIELDS


def test_preview_denies_all_on_a_chain_resolved_for_a_different_article() -> None:
    # Unresolvable binding -> nobody sees it, no fields shown (preview inherits can_view's deny).
    article = _article(audience=Audience(AudienceTier.PUBLIC))
    wrong_chain = ResolvedChain((Collection(ulid="c-other", name="c-other"),))
    p = preview(article, wrong_chain)
    assert p.public is False
    assert p.members is False
    assert p.groups == ()
    assert p.visible_fields == frozenset()


# --- Single-source safety net -----------------------------------------------------------------

_VORSTAND = Audience(AudienceTier.GROUPS, ("vorstand",))


@pytest.mark.parametrize(
    ("viewer", "audience", "lifecycle", "expected"),
    [
        # PUBLISHED, Public rung — everyone sees it.
        (Public(), Audience(AudienceTier.PUBLIC), Lifecycle.PUBLISHED, True),
        (Member(()), Audience(AudienceTier.PUBLIC), Lifecycle.PUBLISHED, True),
        (Archivist(), Audience(AudienceTier.PUBLIC), Lifecycle.PUBLISHED, True),
        # PUBLISHED, Members rung — any Member + Archivist, not Public.
        (Public(), Audience(AudienceTier.MEMBERS), Lifecycle.PUBLISHED, False),
        (Member(()), Audience(AudienceTier.MEMBERS), Lifecycle.PUBLISHED, True),
        (Archivist(), Audience(AudienceTier.MEMBERS), Lifecycle.PUBLISHED, True),
        # Holding groups never narrows a Member out of a Public/Members rung.
        (Member(("vorstand",)), Audience(AudienceTier.PUBLIC), Lifecycle.PUBLISHED, True),
        (Member(("vorstand",)), Audience(AudienceTier.MEMBERS), Lifecycle.PUBLISHED, True),
        # PUBLISHED, Groups rung — only a Member holding the group, plus Archivist.
        (Public(), _VORSTAND, Lifecycle.PUBLISHED, False),
        (Member(("vorstand",)), _VORSTAND, Lifecycle.PUBLISHED, True),
        (Member(("stamm-bonn",)), _VORSTAND, Lifecycle.PUBLISHED, False),
        (Archivist(), _VORSTAND, Lifecycle.PUBLISHED, True),
        # DRAFT — the Lifecycle gate: Archivist only, tier irrelevant.
        (Public(), Audience(AudienceTier.PUBLIC), Lifecycle.DRAFT, False),
        (Member(("vorstand",)), _VORSTAND, Lifecycle.DRAFT, False),
        (Archivist(), Audience(AudienceTier.PUBLIC), Lifecycle.DRAFT, True),
    ],
)
def test_can_view_matrix(
    viewer: Viewer, audience: Audience, lifecycle: Lifecycle, expected: bool
) -> None:
    # The core regression net: Viewer kind x effective tier x Lifecycle, hand-verified.
    article = _article(audience=audience, lifecycle=lifecycle)
    assert can_view(viewer, article, _chain()) is expected


@pytest.mark.parametrize("lifecycle", [Lifecycle.PUBLISHED, Lifecycle.DRAFT])
@pytest.mark.parametrize(
    "audience",
    [Audience(AudienceTier.PUBLIC), Audience(AudienceTier.MEMBERS), _VORSTAND, None],
)
def test_preview_who_sees_is_defined_by_can_view(
    audience: Audience | None, lifecycle: Lifecycle
) -> None:
    # Single-source invariant: preview never re-derives visibility — its flags equal can_view
    # on the published projection. If preview's logic drifted from the resolver, this fails.
    article = _article(audience=audience, lifecycle=lifecycle)
    published = _article(audience=audience, lifecycle=Lifecycle.PUBLISHED)
    p = preview(article, _chain())
    assert p.public == can_view(Public(), published, _chain())
    assert p.members == can_view(Member(), published, _chain())
