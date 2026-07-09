"""The design-token contrast gate (docs/design/design-system.md).

Parses ``static/tokens.css``, resolves every role for BOTH modes to sRGB (stdlib color math in
``color_math``), and asserts the spec table's minimum WCAG 2.1 ratios. The TEST is the source of
truth for the numbers (spec principle: "Contrast is a tested invariant") — tokens.css may retune
its L/C values freely as long as this gate stays green in both modes.

Fails loudly on structural holes: a role expected by the spec table but missing from tokens.css
is an assertion error naming it, and a role referencing an unresolvable ramp raises in the
parser. A silently-skipped role would be a hole in the gate, so there is no skip path.

No database, no Django settings — pure file parsing + math; runs with the normal suite.
"""

from pathlib import Path

import pytest
from tests.app.web.color_math import ResolvedRole, oklch_to_srgb, parse_tokens, wcag_contrast

_TOKENS_CSS = (
    Path(__file__).parents[3] / "src" / "bundesarchiv" / "app" / "web" / "static" / "tokens.css"
)

#: Every role the spec's table + component mapping require. Missing = loud failure.
_EXPECTED_ROLES = frozenset(
    {
        "surface",
        "surface-container-lowest",
        "surface-container-low",
        "surface-container-mid",
        "surface-container-high",
        "on-surface",
        "on-surface-variant",
        "primary",
        "on-primary",
        "primary-container",
        "on-primary-container",
        "draft",
        "on-draft",
        "error",
        "on-error",
        "outline",
        "outline-variant",
        "focus-ring",
    }
)

_SURFACES = (
    "surface",
    "surface-container-lowest",
    "surface-container-low",
    "surface-container-mid",
    "surface-container-high",
)

#: The spec table: (role, paired role, minimum WCAG ratio). "Adjacent surfaces" for outline and
#: "all surfaces" for focus-ring are read as the full surface set — the strictest sensible
#: reading, so a component may put either against any elevation step without a new audit.
_PAIRS: tuple[tuple[str, str, float], ...] = (
    ("surface", "on-surface", 4.5),
    ("surface", "on-surface-variant", 4.5),
    ("surface-container-lowest", "on-surface", 4.5),
    ("surface-container-low", "on-surface", 4.5),
    ("surface-container-mid", "on-surface", 4.5),
    ("surface-container-high", "on-surface", 4.5),
    ("primary", "on-primary", 4.5),
    ("primary-container", "on-primary-container", 4.5),
    ("draft", "on-draft", 4.5),
    ("error", "on-error", 4.5),
    *((surface, "outline", 3.0) for surface in _SURFACES),
    *((surface, "focus-ring", 3.0) for surface in _SURFACES),
)


@pytest.fixture(scope="module")
def roles() -> dict[str, ResolvedRole]:
    return parse_tokens(_TOKENS_CSS.read_text(encoding="utf-8"))


def test_every_expected_role_is_present(roles: dict[str, ResolvedRole]) -> None:
    missing = _EXPECTED_ROLES - roles.keys()
    assert not missing, f"tokens.css is missing spec roles: {sorted(missing)}"


def test_every_pair_role_is_expected() -> None:
    # The pair table may only name roles the presence check covers — a typo here must not
    # silently test nothing.
    named = {name for pair in _PAIRS for name in pair[:2]}
    assert named <= _EXPECTED_ROLES, f"pair table names unknown roles: {named - _EXPECTED_ROLES}"


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("role_a", "role_b", "minimum"), _PAIRS)
def test_contrast_minimums(
    roles: dict[str, ResolvedRole], mode: str, role_a: str, role_b: str, minimum: float
) -> None:
    for name in (role_a, role_b):
        assert name in roles, f"tokens.css is missing role --{name} (required by the pair table)"
    rgb_a = oklch_to_srgb(getattr(roles[role_a], mode))
    rgb_b = oklch_to_srgb(getattr(roles[role_b], mode))
    ratio = wcag_contrast(rgb_a, rgb_b)
    assert ratio >= minimum, (
        f"[{mode}] --{role_a} vs --{role_b}: contrast {ratio:.2f} is under the spec minimum"
        f" {minimum}:1 (oklch {getattr(roles[role_a], mode)} vs {getattr(roles[role_b], mode)})"
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_role_is_inside_srgb_gamut(roles: dict[str, ResolvedRole], mode: str) -> None:
    # An out-of-gamut token would be browser-gamut-mapped to something the gate never measured;
    # oklch_to_srgb raises on gamut escape, so this pins every role to what actually ships.
    for resolved in roles.values():
        oklch_to_srgb(getattr(resolved, mode))  # raises if out of gamut


def test_parser_fails_loudly_on_unresolvable_role() -> None:
    broken = "--seed: oklch(0.55 0.13 300);\n--surface: light-dark(var(--nope), var(--nope));"
    with pytest.raises(ValueError, match="not a resolvable"):
        parse_tokens(broken)


def test_parser_fails_loudly_on_missing_seed() -> None:
    with pytest.raises(ValueError, match="no --seed"):
        parse_tokens("--surface: light-dark(var(--a), var(--b));")
