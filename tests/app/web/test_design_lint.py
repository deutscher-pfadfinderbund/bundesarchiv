"""Design lint — the machine-checkable slice of the design-review law (section E).

Source of the rules: ``docs/design/design-review-law.md`` — cue register B, cascade rules C, and
the explicit lintable subset E. This test parses the PROD stylesheets under
``src/bundesarchiv/app/web/static/`` (the whole styling surface — there are no other stylesheets)
and enforces:

1. no raw colors (hex/rgb/hsl/oklch literals) outside ``tokens.css`` — components consume roles
   only (themability law: component CSS is mode- and theme-blind);
2. square corners: no ``corner-shape`` anywhere, and ``border-radius`` only as the reset ``0``
   (register row 1 retired);
3. ``--error`` consumed only inside register row 5's licensed selectors (allowlisted below —
   extending the allowlist means citing the register row);
4. no ``margin`` on component root selectors (law C4 — compositions own the between);
5. bare px/rem literals outside ``tokens.css`` flagged, except (a) a custom-property DEFINITION
   (naming the dimension IS the C3/C5 mechanism) or (b) a line carrying a comment naming why no
   token fits;
6. no ``box-shadow`` (register rows 8 and 12: flat; a floating panel is ground with an edge) —
   except the doubled edge of an invalid control (register row 5, law E);
7. no compositions-layer selector continues past a component root (law C1/C14 — owned components).
8. a knob is resolved once (law C3): a ``var(--_x)`` needs a ``--_x:`` in the same section, and a
   public knob with a fallback is read only on a ``--_`` line.

The parser is a small brace tracker for OUR OWN formatting (ruff-format-style CSS: one ``{`` per
block opener, selectors and values possibly wrapped over lines). It recurses into
``@layer``/``@media``/``@container`` blocks and records each declaration with its full selector
stack. Proven non-vacuous by mutation during the wave (a planted hex/corner-shape/margin turned
it red).
"""

import itertools
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[3] / "src" / "bundesarchiv" / "app" / "web" / "static"

#: Every prod stylesheet; tokens.css is the ONLY file allowed to write color literals.
STYLESHEETS = ("tokens.css", "components.css", "layouts.css", "forms.css", "detail.css")

#: Register row 5 — red. Selectors that license var(--error), each matched as a whole class
#: (`.error` does not license `.error-banner`).
ERROR_LICENSED = (
    ".error",  # a field error's message (the register's `.field-error`)
    '[aria-invalid="true"]',  # the doubled edge of an invalid control
    ".conflict-notice",  # the edit forms' conflict notice: its heavy rule...
    ".conflict-notice-head",  # ...and its subhead
    ".danger",  # the context on every action that deletes for good
    ".error-banner",  # the failed-request message: an error
)

Decl = tuple[str, str, str, int, bool]  # (selector stack, property, cleaned line, lineno, comment)
#: One at-rule opener: (selector stack including it, the raw condition, lineno, has-comment). Kept
#: SEPARATE from the declarations because an at-rule's CONDITION is not a property/value pair — and
#: because it was invisible to every check while it was only a selector-stack prefix, which is how a
#: hard-coded `@media (min-width: 80rem)` slipped past the px/rem literal rule three times over.
AtRule = tuple[str, str, int, bool]
Rule = tuple[str, str, int]  # (enclosing stack, the rule's own selector list, lineno)


def _parse(css: str) -> tuple[list[Decl], list[AtRule], list[Rule]]:
    """Flatten a stylesheet into declarations, at-rule openers and style-rule openers.

    Declarations are (selector-stack, property, line, lineno, has-comment); at-rules join the stack
    like selectors do, so a rule inside @container still knows its owning selector, AND are returned
    in their own right so the value rules can be run over their conditions. Comments are stripped
    before parsing; whether the original line carried one is kept (the C5 comment exemption)."""
    decls: list[Decl] = []
    at_rules: list[AtRule] = []
    rules: list[Rule] = []
    stack: list[str] = []
    pending: list[str] = []  # selector lines accumulated until their opening brace
    in_comment = False
    in_value = False  # inside a declaration whose value wraps onto further lines
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
        if in_value:
            in_value = not line.endswith(";")
            continue
        if line.endswith("{"):
            pending.append(line[:-1].strip())
            opener = " ".join(p for p in pending if p)
            if opener.startswith("@"):
                at_rules.append((" ".join([*stack, opener]), opener, lineno, had_comment))
            else:
                rules.append((" ".join(stack), opener, lineno))
            stack.append(opener)
            pending = []
            continue
        if line == "}":
            if stack:
                stack.pop()
            continue
        # A declaration is `property:` then whitespace or the line end; `a:hover,` and a wrapped
        # `.chooser:has(…)` are selector lines, as is anything else outside a value.
        match = re.match(r"([-a-zA-Z_][-\w]*)\s*:(?:\s|$)", line)
        if match and stack:
            decls.append((" ".join(stack), match.group(1), line, lineno, had_comment))
            in_value = not line.endswith(";")
            continue
        if not line.endswith(";"):  # a `;` line here is a statement at-rule (`@layer a, b;`)
            pending.append(line)
    return decls, at_rules, rules


def _declarations(css: str) -> list[Decl]:
    return _parse(css)[0]


def _all_declarations() -> dict[str, list[Decl]]:
    return {name: _declarations((STATIC / name).read_text()) for name in STYLESHEETS}


def _all_at_rules() -> dict[str, list[AtRule]]:
    return {name: _parse((STATIC / name).read_text())[1] for name in STYLESHEETS}


def test_every_prod_stylesheet_is_linted() -> None:
    # The list above is hand-written so it can be READ; this makes it a gate rather than a hope. An
    # unlinted stylesheet is the cheapest way for every rule in this file to stop applying, and it
    # arrives silently — a new file just is not in the tuple.
    on_disk = {path.name for path in STATIC.glob("*.css")}
    assert set(STYLESHEETS) == on_disk, (
        f"stylesheets on disk but not linted = {sorted(on_disk - set(STYLESHEETS))}, "
        f"linted but absent = {sorted(set(STYLESHEETS) - on_disk)}"
    )


_COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\(")

#: The CSS named colors. `color: rebeccapurple`, `background: white` and `border-color: red` are raw
#: colors exactly like `#fff` is — the themability law's "no raw hex" is about the token layer being
#: the ONE lever, not about notation — and the hex/function pattern above matched none of them, so all
#: three were green. Kept as data rather than as a "looks like a color word" heuristic: the set is
#: closed and small, and guessing would flag `cover`, `solid` or `dashed`.
_CSS_NAMED_COLORS = frozenset(
    {
        "aliceblue",
        "antiquewhite",
        "aqua",
        "aquamarine",
        "azure",
        "beige",
        "bisque",
        "black",
        "blanchedalmond",
        "blue",
        "blueviolet",
        "brown",
        "burlywood",
        "cadetblue",
        "chartreuse",
        "chocolate",
        "coral",
        "cornflowerblue",
        "cornsilk",
        "crimson",
        "cyan",
        "darkblue",
        "darkcyan",
        "darkgoldenrod",
        "darkgray",
        "darkgreen",
        "darkgrey",
        "darkkhaki",
        "darkmagenta",
        "darkolivegreen",
        "darkorange",
        "darkorchid",
        "darkred",
        "darksalmon",
        "darkseagreen",
        "darkslateblue",
        "darkslategray",
        "darkslategrey",
        "darkturquoise",
        "darkviolet",
        "deeppink",
        "deepskyblue",
        "dimgray",
        "dimgrey",
        "dodgerblue",
        "firebrick",
        "floralwhite",
        "forestgreen",
        "fuchsia",
        "gainsboro",
        "ghostwhite",
        "gold",
        "goldenrod",
        "gray",
        "green",
        "greenyellow",
        "grey",
        "honeydew",
        "hotpink",
        "indianred",
        "indigo",
        "ivory",
        "khaki",
        "lavender",
        "lavenderblush",
        "lawngreen",
        "lemonchiffon",
        "lightblue",
        "lightcoral",
        "lightcyan",
        "lightgoldenrodyellow",
        "lightgray",
        "lightgreen",
        "lightgrey",
        "lightpink",
        "lightsalmon",
        "lightseagreen",
        "lightskyblue",
        "lightslategray",
        "lightslategrey",
        "lightsteelblue",
        "lightyellow",
        "lime",
        "limegreen",
        "linen",
        "magenta",
        "maroon",
        "mediumaquamarine",
        "mediumblue",
        "mediumorchid",
        "mediumpurple",
        "mediumseagreen",
        "mediumslateblue",
        "mediumspringgreen",
        "mediumturquoise",
        "mediumvioletred",
        "midnightblue",
        "mintcream",
        "mistyrose",
        "moccasin",
        "navajowhite",
        "navy",
        "oldlace",
        "olive",
        "olivedrab",
        "orange",
        "orangered",
        "orchid",
        "palegoldenrod",
        "palegreen",
        "paleturquoise",
        "palevioletred",
        "papayawhip",
        "peachpuff",
        "peru",
        "pink",
        "plum",
        "powderblue",
        "purple",
        "rebeccapurple",
        "red",
        "rosybrown",
        "royalblue",
        "saddlebrown",
        "salmon",
        "sandybrown",
        "seagreen",
        "seashell",
        "sienna",
        "silver",
        "skyblue",
        "slateblue",
        "slategray",
        "slategrey",
        "snow",
        "springgreen",
        "steelblue",
        "tan",
        "teal",
        "thistle",
        "tomato",
        "turquoise",
        "violet",
        "wheat",
        "white",
        "whitesmoke",
        "yellow",
        "yellowgreen",
    }
)

#: The color KEYWORDS legitimately in use, which are not raw colors: they resolve against the role
#: layer or against the cascade, so a retint still reaches them (themability law).
_LICENSED_COLOR_KEYWORDS = frozenset(
    {"currentcolor", "transparent", "inherit", "initial", "unset", "revert", "none"}
)


def _value_words(raw: str) -> set[str]:
    """The bare identifiers of a declaration's VALUE, lowercased. `var()` contents are dropped (a role
    token is the licensed shape, and the loud-role rule owns which roles go where), as are quoted
    strings (`content: " · Fehler"` is copy, not a value) and the property name itself."""
    value = raw.split(":", 1)[1] if ":" in raw else raw
    value = re.sub(r"\"[^\"]*\"|'[^']*'", "", value)
    value = re.sub(r"var\([^)]*\)", "", value)
    return {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z-]*", value)}


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
            named = (_value_words(raw) & _CSS_NAMED_COLORS) - _LICENSED_COLOR_KEYWORDS
            if named:
                offenders.append(f"{name}:{lineno}: named color {sorted(named)} — {raw.strip()}")
    assert not offenders, "raw color literal in component CSS (roles only):\n" + "\n".join(
        offenders
    )


#: The one licensed shadow (register row 5, law E): the inset that doubles an invalid control's edge.
SHADOW_LICENSED = '[aria-invalid="true"]'
SHADOW_VALUE = "box-shadow: inset 0 0 0 var(--line-width) var(--error);"


def _shadow_offenders(decls: list[Decl]) -> list[int]:
    return [
        lineno
        for sel, prop, raw, lineno, _comment in decls
        if prop == "box-shadow"
        and not (_licensed(sel, (SHADOW_LICENSED,)) and raw.strip() == SHADOW_VALUE)
    ]


def test_no_box_shadow() -> None:
    offenders = [
        f"{name}:{lineno}"
        for name, decls in _all_declarations().items()
        for lineno in _shadow_offenders(decls)
    ]
    assert not offenders, "box-shadow (register rows 8/12: flat):\n" + "\n".join(offenders)


def test_the_invalid_edge_is_the_only_shadow_licensed() -> None:
    planted = """@layer components {
  .field :is(input, select)[aria-invalid="true"] {
    box-shadow: inset 0 0 0 var(--line-width) var(--error);
  }
  .field [aria-invalid="true"] {
    box-shadow: inset 0 0 0 2px var(--error);
  }
  .panel {
    box-shadow: inset 0 0 0 var(--line-width) var(--error);
  }
}
"""
    assert _shadow_offenders(_declarations(planted)) == [6, 9]


def test_square_corners() -> None:
    offenders = [
        f"{name}:{lineno}: {sel} -> {raw.strip()}"
        for name, decls in _all_declarations().items()
        for sel, prop, raw, lineno, _comment in decls
        if prop == "corner-shape"
        or (prop == "border-radius" and raw.strip() != "border-radius: 0;")
    ]
    assert not offenders, "a corner that is not square (register row 1 retired):\n" + "\n".join(
        offenders
    )


def _licensed(selector: str, allowlist: tuple[str, ...]) -> bool:
    """An entry matches as a whole: never as the prefix of a longer class (`.error-banner`)."""
    return any(re.search(rf"{re.escape(lic)}(?![-\w])", selector) for lic in allowlist)


def test_error_only_in_licensed_selectors() -> None:
    offenders = [
        f"{name}:{lineno} {sel}: {raw.strip()}"
        for name, decls in _all_declarations().items()
        if name != "tokens.css"  # the token layer defines the role
        for sel, _prop, raw, lineno, _comment in decls
        if "var(--error)" in raw and not _licensed(sel, ERROR_LICENSED)
    ]
    assert not offenders, "--error outside register row 5's selectors:\n" + "\n".join(offenders)


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
    # Law C5: --space-*/--touch-target/--touch-target-compact/--line-width/--state-border are the
    # value sources. A bare px/rem literal outside tokens.css needs either a naming custom
    # property (--foo: 3rem — the C3 component-API mechanism) or a same-line comment saying why
    # no token fits.
    #
    # AT-RULE CONDITIONS COUNT. A width threshold is the most consequential literal in the file — C9
    # makes it derive from measured content and carry its arithmetic — and it was the one kind this
    # check could not see, because a condition is not a property/value line. That blind spot is how
    # `@media (min-width: 80rem)` came to exist in three places across two files, one of them not the
    # complement it claimed to be. Every surviving query needs the same C5 comment as any other
    # structural literal: a sentence naming why no token fits.
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
    for name, at_rules in _all_at_rules().items():
        if name == "tokens.css":
            continue
        for _sel, condition, lineno, comment in at_rules:
            if comment:
                continue  # comment-exempted per C5, same rule as any other structural literal
            if _PX_REM.search(condition):
                offenders.append(f"{name}:{lineno}: [at-rule] {condition}")
    assert not offenders, "bare px/rem literal (law C5 — token, name, or comment):\n" + "\n".join(
        offenders
    )


DESIGN_SYSTEM = Path(__file__).resolve().parents[3] / "docs" / "design" / "design-system.md"


def _component_roots() -> tuple[str, ...]:
    """The Root column of design-system.md's component inventory — the one list of components."""
    section = DESIGN_SYSTEM.read_text().split("### Component inventory", 1)[1].split("\n#", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return tuple(row.split("|")[2].strip().strip("`") for row in rows[2:])


def _split_top(selector: str, at: str) -> list[str]:
    """Split at the characters in ``at`` outside any ()/[] — a selector list at ",", a complex
    selector at its combinators."""
    parts, depth, current = [], 0, ""
    for char in selector:
        depth += (char in "([") - (char in ")]")
        if depth == 0 and char in at:
            parts.append(current)
            current = ""
        else:
            current += char
    return [part.strip() for part in [*parts, current] if part.strip()]


def _compounds(complex_selector: str) -> list[str]:
    return _split_top(complex_selector, " >+~")


def _names_root(compound: str, roots: tuple[str, ...]) -> bool:
    """The compound selects a root itself, or through an :is()/:where() argument whose subject does.
    :has()/:not() arguments select other elements, so they never make the compound a root."""
    depths = itertools.accumulate((c == "(") - (c == ")") for c in compound)
    own = "".join(c for c, depth in zip(compound, depths, strict=True) if depth == 0)
    if any(re.search(re.escape(root) + r"(?![-\w])", own) for root in roots):
        return True
    return any(
        _names_root(_compounds(arg)[-1], roots)
        for args in _pseudo_args(compound, ("is", "where"))
        for arg in _split_top(args, ",")
    )


def _pseudo_args(compound: str, names: tuple[str, ...]) -> list[str]:
    found = []
    for match in re.finditer(r":([-\w]+)\(", compound):
        depth, start = 1, match.end()
        end = start
        while depth:
            depth += (compound[end] == "(") - (compound[end] == ")")
            end += 1
        if match.group(1) in names:
            found.append(compound[start : end - 1])
    return found


def _reaches_past_root(complex_selector: str, roots: tuple[str, ...]) -> bool:
    compounds = _compounds(complex_selector)
    if any(_names_root(compound, roots) for compound in compounds[:-1]):
        return True
    return any(
        _reaches_past_root(arg, roots)
        for compound in compounds
        for args in _pseudo_args(compound, ("is", "where", "has", "not"))
        for arg in _split_top(args, ",")
    )


def test_no_composition_selector_reaches_past_a_component_root() -> None:
    # Only a selector that NAMES a root is seen: `.column :is(input, …)` would reach into `.field`
    # without naming it.
    roots = _component_roots()
    found = sorted(
        f"{name}: {' '.join(complex_selector.split())}"
        for name in STYLESHEETS
        for stack, selector_list, _lineno in _parse((STATIC / name).read_text())[2]
        if "@layer compositions" in stack
        for complex_selector in _split_top(selector_list, ",")
        if _reaches_past_root(complex_selector, roots)
    )
    assert not found, (
        "a composition selects inside a component (set its knobs on the root instead):\n"
        + "\n".join(found)
    )


_SECTION_HEAD = re.compile(r"/\* (?:----|====)")
_PRIVATE_DECL = re.compile(r"^\s*(--_[\w-]+)\s*:")
_CUSTOM_DECL = re.compile(r"^\s*--[\w-]+\s*:")
_KNOB_WITH_FALLBACK = re.compile(r"var\(\s*(--(?!_)[\w-]+)\s*,")


def _sectioned_lines(css: str) -> list[tuple[int, int, str]]:
    """(section, lineno, line without comments); a `/* ----` or `/* ====` head opens a section."""
    stripped = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), css, flags=re.DOTALL)
    heads = list(itertools.accumulate(bool(_SECTION_HEAD.search(raw)) for raw in css.splitlines()))
    return [(heads[i], i + 1, line) for i, line in enumerate(stripped.splitlines())]


def test_a_private_knob_is_declared_in_its_own_section() -> None:
    # Law C3: a component resolves each knob once, into a `--_name` at the top of its section.
    # Reading a `--_name` the section never declares reads one some other component resolved.
    offenders = []
    for name in STYLESHEETS:
        lines = _sectioned_lines((STATIC / name).read_text())
        declared = {
            (section, m.group(1)) for section, _n, line in lines if (m := _PRIVATE_DECL.match(line))
        }
        offenders += [
            f"{name}:{lineno}: {private}"
            for section, lineno, line in lines
            for private in re.findall(r"var\(\s*(--_[\w-]+)", line)
            if (section, private) not in declared
        ]
    assert not offenders, "a --_name read without its section's declaration (C3):\n" + "\n".join(
        offenders
    )


def test_a_public_knob_is_read_only_where_it_is_resolved() -> None:
    # Law C3: the knob's fallback lives on its one `--_` line; every rule reads the `--_` name. A
    # fallback elsewhere is a second default, and a bare read elsewhere skips the default (G.38,
    # G.45). Handing the knob on to another knob (`--a: var(--b)`) is a parent setting a knob.
    lines = [
        (name, lineno, line)
        for name in STYLESHEETS
        for _s, lineno, line in _sectioned_lines((STATIC / name).read_text())
    ]
    knobs = {
        knob
        for _f, _n, line in lines
        if _PRIVATE_DECL.match(line)
        for knob in _KNOB_WITH_FALLBACK.findall(line)
    }
    offenders = [
        f"{name}:{lineno}: {line.strip()}"
        for name, lineno, line in lines
        if not _PRIVATE_DECL.match(line)
        and (
            _KNOB_WITH_FALLBACK.search(line)
            or (
                not _CUSTOM_DECL.match(line)
                and any(re.search(rf"var\(\s*{knob}\s*\)", line) for knob in knobs)
            )
        )
    ]
    assert not offenders, "a public knob read outside its --_ line (C3):\n" + "\n".join(offenders)
