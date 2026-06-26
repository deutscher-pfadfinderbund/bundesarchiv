"""Viewer-facing access predicate — `can_view` composes effective_audience + Viewer.

Fail-closed (ADR 0001): a non-Published Article is Archivist-only; an unresolvable chain
denies everyone. Fixture-driven, no IO. The chain is leaf-first as resolve_chain returns it.
"""

from dataclasses import fields

from bundesarchiv.domain.access import ARCHIVIST_ONLY_FIELDS, can_view, project
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public


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


def _chain(collection_id: str = "c-leaf") -> tuple[Collection, ...]:
    # A single root Collection that owns the Article — a minimal valid resolved chain.
    return (Collection(ulid=collection_id, name=collection_id),)


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


def test_can_view_denies_everyone_on_an_empty_chain() -> None:
    # effective_audience raises MisresolvedChain; can_view catches and denies — fail closed.
    # Even an Archivist is denied: there is no resolvable Audience to gate on.
    article = _article(audience=Audience(AudienceTier.PUBLIC))
    assert can_view(Public(), article, ()) is False
    assert can_view(Member(("vorstand",)), article, ()) is False
    assert can_view(Archivist(), article, ()) is False


def test_can_view_denies_everyone_on_a_misresolved_chain() -> None:
    # A chain whose leaf is not the Article's Collection is a wiring bug — deny, don't raise.
    article = _article(collection_id="c-leaf", audience=Audience(AudienceTier.PUBLIC))
    wrong_chain = (Collection(ulid="c-other", name="c-other"),)
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
        physical_description="Schwarz-weiß-Abzug, 13x18",
    )


def test_project_floors_archivist_only_fields_for_a_member() -> None:
    projected = project(Member(), _physical_article())
    assert projected.physical_location is None
    assert projected.physical_description is None


def test_project_floors_archivist_only_fields_for_public() -> None:
    projected = project(Public(), _physical_article())
    assert projected.physical_location is None
    assert projected.physical_description is None


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
