"""Design lint — the machine-checkable slice of the design-review law (section E).

Source of the rules: ``docs/design/design-review-law.md`` — cue register B, cascade rules C, and
the explicit lintable subset E. This test parses the PROD stylesheets under
``src/bundesarchiv/app/web/static/`` (the whole styling surface — there are no other stylesheets)
and enforces:

1. no raw colors (hex/rgb/hsl/oklch literals) outside ``tokens.css`` — components consume roles
   only (themability law: component CSS is mode- and theme-blind);
2. ``corner-shape`` only inside register row 1's licensed selector (``.c-sig`` — the sole bevel
   carrier since the 2026-08-07 register amendment);
3. ``--primary`` / ``--draft`` / ``--error`` consumed only inside rows 2/4/5's licensed selector
   families (allowlisted below — extending an allowlist means citing a register row);
4. no ``margin`` on component root selectors (law C4 — compositions own the between);
5. bare px/rem literals outside ``tokens.css`` flagged, except (a) a custom-property DEFINITION
   (naming the dimension IS the C3/C5 mechanism) or (b) a line carrying a comment naming why no
   token fits;
6. ``box-shadow`` appears only as consumption of ``var(--sheet-shadow)`` (register row 8: the
   resting-contact shadow is the ONE depth cue; Material elevation ramps are forbidden).

The parser is a small brace tracker for OUR OWN formatting (ruff-format-style CSS: one ``{`` per
block opener, selectors possibly wrapped over lines, declarations one per line). It recurses into
``@layer``/``@media``/``@container`` blocks and records each declaration with its full selector
stack. Proven non-vacuous by mutation during the wave (a planted hex/corner-shape/margin turned
it red).
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[3] / "src" / "bundesarchiv" / "app" / "web" / "static"

#: Every prod stylesheet; tokens.css is the ONLY file allowed to write color literals.
STYLESHEETS = ("tokens.css", "components.css", "layouts.css", "forms.css", "detail.css")

#: Register row 1 — the bevel cut's one licensed selector (2026-08-07 amendment: `.c-facet-tab`
#: no longer exists in live markup and lost its license).
ROW1_BEVEL = ("c-sig",)

#: Row 2 — violet ink: the Signatur code, mono counts/dates, inline links, plus the roles that
#: legitimately embed primary at the token layer. Selector substrings that license var(--primary).
PRIMARY_LICENSED = (
    ".c-sig-code",  # the Signatur code (row 2, named)
    "a",  # inline links (row 2, named) — element default + link-styled buttons
    ".datierung",  # ledger mono date cells (row 2: mono dates)
    "dd.mono",  # detail record-card mono machine values (row 2: mono dates)
    ".filmstrip h2 span",  # the mono Blatt count (row 2: mono counts)
    ".pane h2 + p",  # the pane's mono meta line (row 2: mono dates)
    ".file > span",  # media register filename — the mono data mark (row 2)
    "button.link",  # link-styled buttons — inline interactive text (row 2)
    ".echo",  # EDTF echo may carry one violet fragment (spec §0)
)

#: Row 4 — amber: the ENTWURF lifecycle badge ONLY.
DRAFT_LICENSED = (".badge.entwurf",)

#: Row 5 — red: errors (field errors via .error/.field, the CAS konflikt panel, the failure
#: banner, the destructive confirm button — forms spec §7's one filled variant).
ERROR_LICENSED = (".error", ".field:has(.error)", ".konflikt", ".danger", "button.danger")

Decl = tuple[str, str, str, int, bool]  # (selector stack, property, cleaned line, lineno, comment)


def _declarations(css: str) -> list[Decl]:
    """Flatten a stylesheet into (selector-stack, property, line, lineno, has-comment) tuples.
    At-rules join the stack like selectors do, so a rule inside @container still knows its owning
    selector. Comments are stripped before parsing; whether the original line carried one is kept
    (the C5 comment exemption)."""
    decls: list[Decl] = []
    stack: list[str] = []
    pending: list[str] = []  # selector lines accumulated until their opening brace
    in_comment = False
    for lineno, raw in enumerate(css.splitlines(), start=1):
        line = raw
        had_comment = "/*" in line or in_comment
        if in_comment:
            if "*/" not in line:
                continue
            line = line.split("*/", 1)[1]
            in_comment = False
        line = re.sub(r"/\*.*?\*/", "", line)
        if "/*" in line:
            line = line.split("/*", 1)[0]
            in_comment = True
        line = line.strip()
        if not line:
            continue
        if line.endswith("{"):
            pending.append(line[:-1].strip())
            stack.append(" ".join(p for p in pending if p))
            pending = []
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        if line.endswith(",") or (not line.endswith(";") and ":" not in line):
            pending.append(line)  # a wrapped selector line
            continue
        match = re.match(r"([-a-zA-Z_][-\w]*)\s*:", line)
        if match and stack:
            decls.append((" ".join(stack), match.group(1), line, lineno, had_comment))
    return decls


def _all_declarations() -> dict[str, list[Decl]]:
    return {name: _declarations((STATIC / name).read_text()) for name in STYLESHEETS}


_COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\(")


def test_no_raw_colors_outside_tokens() -> None:
    offenders = []
    for name, decls in _all_declarations().items():
        if name == "tokens.css":
            continue
        for _sel, _prop, raw, lineno, _comment in decls:
            # color-mix over ROLES is licensed ("the only color functions are var() over roles and
            # color-mix() OVER roles"); any absolute color function/hex is not.
            candidate = re.sub(r"color-mix\([^)]*\)", "", raw)
            if _COLOR_LITERAL.search(candidate):
                offenders.append(f"{name}:{lineno}: {raw.strip()}")
    assert not offenders, "raw color literal in component CSS (roles only):\n" + "\n".join(
        offenders
    )


def test_box_shadow_only_the_sheet_shadow_token() -> None:
    # Register row 8: EXACTLY ONE depth cue — the resting-contact shadow. Component CSS may
    # consume the token (`box-shadow: var(--sheet-shadow);`) and nothing else: no literal shadow
    # values, no elevation stacks (the Material float model is forbidden everywhere). tokens.css
    # is exempt — it DEFINES the token.
    offenders = []
    for name, decls in _all_declarations().items():
        if name == "tokens.css":
            continue
        for sel, prop, raw, lineno, _comment in decls:
            if prop == "box-shadow" and raw.strip() != "box-shadow: var(--sheet-shadow);":
                offenders.append(f"{name}:{lineno}: {sel} -> {raw.strip()}")
    assert not offenders, "box-shadow outside var(--sheet-shadow) (register row 8):\n" + "\n".join(
        offenders
    )


def test_corner_shape_only_on_register_row_1_selectors() -> None:
    offenders = []
    for name, decls in _all_declarations().items():
        for sel, prop, raw, lineno, _comment in decls:
            if prop == "corner-shape" and not any(f".{lic}" in sel for lic in ROW1_BEVEL):
                offenders.append(f"{name}:{lineno}: {sel} -> {raw.strip()}")
    assert not offenders, "corner-shape outside register row 1's selectors:\n" + "\n".join(
        offenders
    )


def _licensed(selector: str, allowlist: tuple[str, ...]) -> bool:
    return any(lic in selector for lic in allowlist)


def test_loud_roles_only_in_licensed_selectors() -> None:
    offenders = []
    for name, decls in _all_declarations().items():
        if name == "tokens.css":
            continue  # the token layer derives roles from roles by definition
        for sel, _prop, raw, lineno, _comment in decls:
            if "var(--primary)" in raw and not _licensed(sel, PRIMARY_LICENSED):
                offenders.append(f"{name}:{lineno} [row 2] {sel}: {raw.strip()}")
            if re.search(r"var\(--(?:draft|on-draft)\)", raw) and not _licensed(
                sel, DRAFT_LICENSED
            ):
                offenders.append(f"{name}:{lineno} [row 4] {sel}: {raw.strip()}")
            if re.search(r"var\(--(?:error|on-error)\)", raw) and not _licensed(
                sel, ERROR_LICENSED
            ):
                offenders.append(f"{name}:{lineno} [row 5] {sel}: {raw.strip()}")
    assert not offenders, "loud role consumed outside its register row's selectors:\n" + "\n".join(
        offenders
    )


def test_no_margin_on_component_roots() -> None:
    # Law C4: components own the inside; compositions own the between. A component ROOT (a rule in
    # the components layer whose subject is one bare class) must not declare outer margins.
    # .visually-hidden is exempt: its -1px margin is part of the off-screen sr-only clip
    # technique, not surface spacing.
    offenders = []
    for name, decls in _all_declarations().items():
        for sel, prop, raw, lineno, _comment in decls:
            if "@layer components" not in sel or ".visually-hidden" in sel:
                continue
            subject = sel.split("@layer components", 1)[1].strip()
            if re.fullmatch(r"\.[a-z][-\w]*", subject) and re.fullmatch(
                r"margin(-top|-right|-bottom|-left|-block.*|-inline.*)?", prop
            ):
                offenders.append(f"{name}:{lineno}: {subject} -> {raw.strip()}")
    assert not offenders, "external margin on a component root (law C4):\n" + "\n".join(offenders)


_PX_REM = re.compile(r"\b(?:0*[1-9]\d*(?:\.\d+)?|0?\.\d+)(?:px|rem)\b")


def test_bare_dimension_literals_are_named_or_commented() -> None:
    # Law C5: --space-*/--touch-target/--hairline/--state-border are the value sources. A bare
    # px/rem literal outside tokens.css needs either a naming custom property (--foo: 3rem — the
    # C3 component-API mechanism) or a same-line comment saying why no token fits.
    offenders = []
    for name, decls in _all_declarations().items():
        if name == "tokens.css":
            continue
        for sel, prop, raw, lineno, comment in decls:
            if prop.startswith("--"):
                continue  # a named local dimension (law C3) — the naming IS the exemption
            if comment:
                continue  # comment-exempted per C5
            if _PX_REM.search(raw):
                offenders.append(f"{name}:{lineno}: {sel} -> {raw.strip()}")
    assert not offenders, "bare px/rem literal (law C5 — token, name, or comment):\n" + "\n".join(
        offenders
    )
