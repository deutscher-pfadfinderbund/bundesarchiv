"""Viewer-facing access predicate — `can_view` composes effective_audience + Viewer.

Fail-closed (ADR 0001): a non-Published Article is Archivist-only; an unresolvable chain
denies everyone. Fixture-driven, no IO. The chain is leaf-first as resolve_chain returns it.
"""

from bundesarchiv.domain.access import can_view
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
