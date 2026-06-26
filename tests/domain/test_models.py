"""Domain value-object construction invariants (illegal states unrepresentable)."""

import pytest

from bundesarchiv.domain.models import Audience, AudienceTier


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
