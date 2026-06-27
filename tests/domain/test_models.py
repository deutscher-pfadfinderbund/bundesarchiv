"""Domain value-object construction invariants (illegal states unrepresentable)."""

import pytest

from bundesarchiv.domain.models import Article, Audience, AudienceTier


def test_groups_tier_requires_at_least_one_named_group() -> None:
    # GROUPS with no group named would mean "narrow Members to nobody" — a cataloging
    # mistake, not a rung. Forbid it at construction.
    with pytest.raises(ValueError):
        Audience(AudienceTier.GROUPS, ())


@pytest.mark.parametrize("tier", [AudienceTier.PUBLIC, AudienceTier.MEMBERS])
def test_non_groups_tier_rejects_named_groups(tier: AudienceTier) -> None:
    # PUBLIC/MEMBERS + a named group is contradictory: a tier-first reader silently
    # ignores the group, so the cataloger believes they restricted it but did not.
    with pytest.raises(ValueError):
        Audience(tier, ("geheim",))


def test_valid_audiences_construct() -> None:
    assert Audience().tier is AudienceTier.MEMBERS  # default rung, no groups
    Audience(AudienceTier.PUBLIC)
    Audience(AudienceTier.GROUPS, ("bundesfuehrung",))
    Audience(AudienceTier.GROUPS, ("bundesfuehrung", "landesfuehrung"))


def test_groups_is_normalized_to_a_tuple() -> None:
    # A frozen, hashable value object must not store a list (unhashable, and unequal to its
    # tuple twin) even when built from one via dynamic/untyped input.
    built_from_list = Audience(AudienceTier.GROUPS, ["bundesfuehrung"])  # type: ignore[arg-type]
    assert isinstance(built_from_list.groups, tuple)
    assert built_from_list == Audience(AudienceTier.GROUPS, ("bundesfuehrung",))
    assert hash(built_from_list) == hash(Audience(AudienceTier.GROUPS, ("bundesfuehrung",)))


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_group_names_are_rejected(blank: str) -> None:
    # A blank Keycloak group name narrows Members to a group that cannot exist — a cataloging
    # mistake (and leak-adjacent), so reject it rather than store nobody.
    with pytest.raises(ValueError):
        Audience(AudienceTier.GROUPS, ("vorstand", blank))


def test_duplicate_group_names_are_deduplicated() -> None:
    # Groups are OR-combined (set semantics); a duplicate is redundant. Dedupe so equal group
    # sets yield equal, equally-hashing Audiences.
    deduped = Audience(AudienceTier.GROUPS, ("vorstand", "vorstand"))
    assert deduped.groups == ("vorstand",)
    assert deduped == Audience(AudienceTier.GROUPS, ("vorstand",))


def _article(**custom_pairs: object) -> Article:
    return Article(ulid="01J0", title="t", collection_id="c", custom=tuple(custom_pairs.items()))  # type: ignore[arg-type]


def test_custom_fields_are_sorted_and_deduped() -> None:
    # Order-independent + canonical: sorted by key, last value wins on a duplicate key.
    article = Article(
        ulid="01J0", title="t", collection_id="c", custom=(("zeta", "1"), ("alpha", "2"))
    )
    assert article.custom == (("alpha", "2"), ("zeta", "1"))


def test_custom_field_values_are_coerced_to_str() -> None:
    assert _article(jahr=1955).custom == (("jahr", "1955"),)


def test_custom_key_colliding_with_a_predefined_field_is_rejected() -> None:
    # A custom key must not masquerade as a predefined field (e.g. the visible `title`).
    with pytest.raises(ValueError):
        _article(title="sneaky")
