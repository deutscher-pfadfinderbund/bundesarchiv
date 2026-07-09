"""Color math + tokens.css parsing for the design-token contrast gate (test helper, stdlib only).

Two halves:

- ``oklch_to_srgb`` / ``wcag_contrast`` — the deterministic conversion chain OKLCH → OKLab →
  linear sRGB → gamma-encoded sRGB, then WCAG 2.1 relative-luminance contrast. Constants are the
  published OKLab matrices (Björn Ottosson) and the WCAG 2.1 formulas verbatim; no dependency.
- ``parse_tokens`` — a deliberately narrow parser for the tokens.css format contract (documented
  in that file's header): seed line, ramp entries (relative-to-seed or absolute oklch), role
  entries (``light-dark(var(--a), var(--b))``). It resolves every role to concrete (L, C, H)
  numbers per mode and FAILS LOUDLY (raises) on anything unresolvable — a silently-skipped role
  would be a hole in the contrast gate.

All tokens are kept inside sRGB gamut by construction (tokens.css eases chroma at the L
extremes); the conversion clips defensively but the gate is meaningful only for in-gamut values,
so ``oklch_to_srgb`` also reports gamut escape via ``assert_in_gamut``.
"""

import math
import re
from dataclasses import dataclass

type Oklch = tuple[float, float, float]  # (L, C, H-degrees)
type Rgb = tuple[float, float, float]  # gamma-encoded sRGB, each 0..1


def oklch_to_srgb(color: Oklch, *, assert_in_gamut: bool = True) -> Rgb:
    """Convert an OKLCH color to gamma-encoded sRGB (0..1 per channel).

    OKLCH → OKLab (polar→cartesian), OKLab → LMS' (cube roots undone), LMS → linear sRGB
    (Ottosson's published matrices), then the sRGB transfer function. With
    ``assert_in_gamut`` (the default) a channel escaping [0,1] by more than rounding noise
    raises — the gate must never silently clip a token into passing."""
    lightness, chroma, hue_deg = color
    a = chroma * math.cos(math.radians(hue_deg))
    b = chroma * math.sin(math.radians(hue_deg))
    # OKLab → non-linear LMS (l', m', s'), then cube to linear LMS.
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    lin_l, lin_m, lin_s = l_**3, m_**3, s_**3
    # linear LMS → linear sRGB.
    r_lin = +4.0767416621 * lin_l - 3.3077115913 * lin_m + 0.2309699292 * lin_s
    g_lin = -1.2684380046 * lin_l + 2.6097574011 * lin_m - 0.3413193965 * lin_s
    b_lin = -0.0041960863 * lin_l - 0.7034186147 * lin_m + 1.7076147010 * lin_s

    def encode(channel: float) -> float:
        channel = max(0.0, channel)
        if channel <= 0.0031308:
            return 12.92 * channel
        return 1.055 * math.pow(channel, 1 / 2.4) - 0.055

    encoded = (encode(r_lin), encode(g_lin), encode(b_lin))
    if assert_in_gamut and any(not (-0.002 <= c <= 1.002) for c in encoded):
        raise ValueError(f"oklch{color} is outside sRGB gamut: rgb={encoded}")
    return (
        min(1.0, max(0.0, encoded[0])),
        min(1.0, max(0.0, encoded[1])),
        min(1.0, max(0.0, encoded[2])),
    )


def wcag_contrast(rgb1: Rgb, rgb2: Rgb) -> float:
    """WCAG 2.1 contrast ratio between two gamma-encoded sRGB colors: (L1+0.05)/(L2+0.05) over
    relative luminance, using the spec's linearization (threshold 0.03928) verbatim."""

    def luminance(rgb: Rgb) -> float:
        def linear(channel: float) -> float:
            if channel <= 0.03928:
                return channel / 12.92
            return math.pow((channel + 0.055) / 1.055, 2.4)

        r, g, b = (linear(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lighter, darker = sorted((luminance(rgb1), luminance(rgb2)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@dataclass(frozen=True, slots=True)
class ResolvedRole:
    """One role token resolved to concrete OKLCH numbers for both modes."""

    light: Oklch
    dark: Oklch


# The tokens.css format contract, as regexes. Deliberately narrow: anything the file adds that
# these do not match is simply not a color token (spacing, type, shape) — but a ROLE that fails
# to resolve raises in parse_tokens, never skips.
_SEED_RE = re.compile(r"--seed:\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)")
_RELATIVE_RE = re.compile(
    r"--([a-z0-9-]+):\s*oklch\(\s*from\s+var\(--seed\)\s+([\d.]+)\s+([\d.]+|c)\s+h\s*\)"
)
_ABSOLUTE_RE = re.compile(r"--([a-z0-9-]+):\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)")
_ROLE_RE = re.compile(
    r"--([a-z0-9-]+):\s*light-dark\(\s*var\(--([a-z0-9-]+)\),\s*var\(--([a-z0-9-]+)\)\s*\)"
)


def parse_tokens(css: str) -> dict[str, ResolvedRole]:
    """Parse tokens.css into role name → resolved light/dark OKLCH.

    Raises (fails the gate loudly) when the seed is missing or a role references a ramp entry
    that does not exist — a role silently resolving to nothing must never pass."""
    seed_match = _SEED_RE.search(css)
    if seed_match is None:
        raise ValueError("tokens.css: no --seed found — the format contract is broken")
    seed = (float(seed_match.group(1)), float(seed_match.group(2)), float(seed_match.group(3)))

    ramps: dict[str, Oklch] = {"seed": seed}
    for name, lightness, chroma in _RELATIVE_RE.findall(css):
        resolved_chroma = seed[1] if chroma == "c" else float(chroma)
        ramps[name] = (float(lightness), resolved_chroma, seed[2])
    for name, lightness, chroma, hue in _ABSOLUTE_RE.findall(css):
        if name == "seed":
            continue
        ramps[name] = (float(lightness), float(chroma), float(hue))

    roles: dict[str, ResolvedRole] = {}
    for role, light_ref, dark_ref in _ROLE_RE.findall(css):
        for ref in (light_ref, dark_ref):
            if ref not in ramps:
                raise ValueError(
                    f"tokens.css: role --{role} references --{ref}, which is not a resolvable"
                    f" ramp entry — the contrast gate cannot cover it (format contract broken)"
                )
        roles[role] = ResolvedRole(light=ramps[light_ref], dark=ramps[dark_ref])
    return roles
