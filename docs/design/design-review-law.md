# Design review rules

Status: agent-written working document (since 2026-08-06), not ratified by the owner as a
whole; the owner may change any of it at any time. It is in force to the extent the design
gate and the design lint (`tests/app/web/test_design_lint.py`, section E) run against it.
The enforceable half of `design-system.md`: how any UI change is reviewed, which visual cues
are licensed and where, and when to use which styling mechanism. Written to bind an agent
with NO other context — a reviewer gets this file and the code, nothing else.

Rules first, fixes later: existing CSS is *measured* against this document; bringing it
into compliance is the rework wave's job, not a side effect of a review.

**Framework vs. contents (owner, 2026-08-06):** this document is first and
foremost a framework for agents. The *mechanisms* are binding — the
catechism, the register discipline (cues need rows, rows are owner
decisions), the cascade rules, themability, the availability tiers. The
*contents* — which register rows exist, the material, the motion
vocabulary — are the CURRENT design state: owner-changeable at any time,
final design up for debate. An agent may never change contents on its own;
an owner may always.

**Unit of review:** a component is the triple **template + its dedicated CSS
block + all live usages**. A verdict names which part it applies to. Tracing
live callers is in scope — a component cannot be judged without its citizens.

## A. The review catechism

Ask in order; earlier questions can terminate the review.

1. **Does it appear in a live flow?** A template referenced only by demo
   pages is an exhibit, not a citizen → park-or-delete verdict. CSS classes
   consumed by live templates stay in scope even when the template is an
   exhibit.
2. **What fact does each element show — and is this the only place that
   fact appears on the surface?** One fact, one place. Duplication is a
   defect (e.g. a Signatur tab plus a "Signatur …" meta line on one card).
3. **Who needs the fact, at that moment?** Which viewer tier/role? Archivist
   chrome never leaks into member views, and vice versa.
4. **Is the default state marked or quiet?** Mark deviations only; stamping
   the normal case is noise.
5. **What rule places every distinctive cue — can a cue-register row be
   cited, selector and position included?** A cue without a row is noise.
6. **Does interaction styling match actual interactivity?** No false
   affordances (hover on non-clickable containers), no dead styling (a cue
   that renders invisibly in every state).
7. **What does absence look like?** The component itself defines its empty
   rendering (collapse, placeholder, or the hollow state); callers may
   additionally suppress it upstream, but may not be the only defense.
8. **Do all gaps come from the spacing scale — and does the parent own the
   between?**
9. **Does every element's visual weight match its information rank for the
   primary user of this surface?** Placement and size are claims of
   importance ("3 Treffer" in the headline spot is a false claim). Rank by
   how often the primary user needs it, not by when it was built.
10. **How many interactions does the most frequent task cost?** The primary
   loop (archivist: open an article) must be the shortest path on the
   surface. A preview or intermediate step is an enhancement, never a toll
   gate.

**Severity:** findings are reported ranked —
- **S1**: dead/exhibit code, contradiction with recorded law, false
  affordance.
- **S2**: cue-register or cascade-rule violation.
- **S3**: lintable value defect (raw literals).

## B. Cue register

The complete list of licensed visual cues. Semantics are **MAY-only**: a row
licenses a cue at the named selectors and positions; it never obliges its
use, and absence of a cue is always legal. Rows name **selectors**, not
prose. Any distinctive cue without a row is an S2 defect; adding a cue means
adding a row first, and rows are owner decisions.

**Monochrome amendment (owner, 2026-09-27).** The register below is the "Druckschwarz" state
(`design-system.md`, `DESIGN.md`). Rows keep their numbers; a retired row stays as a record and
licenses nothing. The retoken wave (Wave T, 2026-09-27) moved the app's tokens and the design
lint (E) onto these rows; components still carrying retired cues are listed in `docs/tech-debt.md`
#20 and change with their component wave.

| # | Cue | Licensed selectors + position | Everywhere else |
|---|-----|-------------------------------|-----------------|
| 1 | Bevel cut | **RETIRED** (2026-09-27: square corners everywhere). History: the Signatur tab's leading cut, demoted 2026-08-29. | forbidden |
| 2 | Violet ink | **RETIRED** (2026-09-27: no second hue). Signaturen, counts and dates render in ink; links are underlined ink. | forbidden |
| 3 | Inversion (solid fg/bg swap) | light only: the primary button (`.button-primary`, and every `.button` on hover; dark never fills with ink, a hover lifts to a dim ground); the active option of a suggestion list (`.autocomplete-list [aria-selected="true"]`) | forbidden — never a hover wash on rows, never a filter chip |
| 4 | Amber | **RETIRED** (2026-09-27). "Entwurf" is a mark in words (`.mark`, secondary ink). | forbidden |
| 5 | Red (`--error`) | field errors (`.error`); the doubled edge of `[aria-invalid="true"]` controls and of an autocomplete box holding one; the edit-conflict notice (`.conflict-notice`: its 3px top rule and its subhead); whatever carries the `.danger` context, on hover, press and focus (the × of `.remove` and of a chip, the menu's "Löschen", the delete confirm's button) | forbidden — not for warnings or emphasis |
| 6 | Dashed border | only something that reacts (owner ruling 2026-10-01: a dashed frame or an underline — at least on hover — marks interactive things only); none today | forbidden — never on an empty slot, a read-only fact or decoration |
| 7 | Quiet default | the published / normal state renders no mark | — |
| 8 | Paper sheet material | **RETIRED** (2026-09-27: flat — no tint, no shadow). | forbidden — no shadow, gradient, glow or texture anywhere |
| 9 | Icons | ONE stroke set (24px grid, stroke 2, `currentColor`; app `components/icon.html`, mock `system/icons.svg`, name for name). Slots: row toolbars (`role="toolbar"`, the media row tools), the removing × (`.remove`). Every icon-only control names itself. | forbidden — no icon fonts, no second style |
| 10 | Pane-row marker | **SUSPENDED** until the list page is recomposed (the preview pane itself is an open question; its token `--surface-container-high` has no monochrome role). | forbidden |
| 11 | Ledger margin rule | **RETIRED** (2026-09-29, the list wave: the a2 list the owner reviewed has no vertical rule; the Signatur is a quiet column near the end). History: one vertical hairline after the leading Signatur column. | forbidden — no vertical rules |
| 12 | Floating panel edge | **AMENDED** (was the overlay shadow; 2026-09-27 the edge went from `--edge` to `--ink`: a panel is never quieter than the control that opened it): transient panels are page surface with a 1px `--ink` border, in the top layer via the native popover — the menu (`ul.menu[popover]`), the help popover (`.popover`), the tool panel (`.toolpanel`), the suggestion list (`.autocomplete-list`) | forbidden — no shadow on anything |
| 13 | Sort glyph | the direction glyph on the sortable head carrying the active sort; on other sortable heads only on hover / focus (`.ledger th > a`) | forbidden — no step-up of the sorted column |
| 14 | Hairline row rule | `--rule` 1px between the rows of a register or ledger that have two ends (a lead and a figure) | forbidden — never above the first or below the last row, never under headers, filter bars or section heads |
| 15 | Heavy rule | 3px, `--error`: the top of the edit-conflict notice only (`.conflict-notice`) | forbidden — section rules were removed (`r3-linien`) |
| 16 | Help mark ⓘ | the character U+24D8 at the end of a field hint (`.help`), opening a `.popover` | forbidden — no "?" glyphs, no hover-only tooltips; exception: a `<time>` that shows its date may add the time on hover (owner, 2026-10-21) |
| 17 | Note | `.note` (note type, `--ink-3`) touching a label or heading ("intern") | forbidden — never at a far edge, never boxed |
| 18 | Placeholder cross | `--placeholder` in `--faint` on an item without an image (`.blank`, `.file-row-thumb`) | forbidden — no placeholder where no medium is expected |
| 19 | Gray fill | **RETIRED** (owner 2026-09-27: the door's login is a primary button). | forbidden |
| 20 | Underline | links and crumb steps at rest; text controls (menu entries, "+ …", suggestion options, field asides) on hover only | forbidden as decoration |

**Reserved (recorded, NOT licensed):** none open. The serif reading role reserved for the
Lesesaal composition lapsed into the monochrome type roles (serif for headings and titles); the
trapezoid register tab lapsed with the square-corner ruling.

## C. Cascade rules — when to use which styling

1. **Elements first.** Semantic HTML is styled via element + context
   selectors. A class exists only where semantics cannot express the
   distinction — and on a component's root: its outer element carries one
   class named for the component, and compositions select that root and
   never past it (owner, 2026-09-25; the roots: `design-system.md`,
   "Component inventory"). Inside a component, elements first still holds.
2. **Context over variants.** A component adapts to where it sits (ancestor
   scope, `@container`), never via variant modifier classes. A context may sit on
   the element itself: `.danger` re-points `--ink` to `--error` and sets no property,
   so `.button`, `.remove` and a menu entry turn red without knowing it; `.quiet`
   re-points `--ink` to `--ink-2` for a fact, a row or a section (2026-09-27). The test: a context re-points roles or knobs and works on any
   component; a variant sets one component's own properties (`.button-danger`). **State
   modifiers are exempt**: a class encoding runtime state (`--aktiv`) is
   legal — but prefer styling on `aria-current`/`aria-selected`/`[hidden]`
   where the attribute exists, so state and styling cannot drift apart.
3. **Custom properties are the component API.** Parents set knobs
   (`--gap`, `--density`); children consume them. Variation travels down
   through properties, not through new selectors.
   **A knob is resolved once per component** (owner, 2026-10-01): the rule that reads
   it declares `--_height: var(--control-height, var(--touch-target));` first and then
   reads only `--_height`, never the public knob and never a second fallback. Each
   component section uses its own `--_` names: a shared one would let one rule's
   default reach another rule's element. One default per knob per component, so two rules cannot resolve it
   differently. A component declares every `--_` name it reads; it never
   reads one an ancestor set. Source: Lea Verou, "Custom properties with defaults"
   (2021), pseudo-private properties. Not `@property`: registration is global.
4. **Components own the inside; compositions own the between.** No external
   margins on components. Clearance for a component's own positioned parts
   is internal spacing and comes from the scale like everything else.
5. **Tokens are the only value source.** Spacing from `--space-*`. The
   non-spacing dimensions have named tokens: `--touch-target` (2.75rem),
   `--touch-target-compact` (2rem — the row knob of the header and of every page action row;
   owner rulings 2026-08-07, rail round 2, and 2026-10-01), `--line-width` (1px),
   `--state-border` (3px). A dimension used once,
   structurally, may be a literal **with a comment naming why no token
   fits**; a bare literal is an S3 defect. This binds **at-rule conditions**
   too — a width threshold is the most consequential literal in a stylesheet
   (see C9) and is linted like any other (section E).
   **Stacking is one scale, `--z-*` in `tokens.css`** (recorded 2026-08-08;
   owner may veto): a bare `z-index` is a literal whose RELATIONSHIP to its
   neighbours is its entire meaning, so the model is stated once, in order —
   flow (incl. the sticky sheet) < a dropped overlay panel < a sticky control
   row < the page header < the viewport-fixed banner. A new layer joins the
   scale; it is never guessed at its use site. (The header must out-stack the
   rows because a sticky row is a stacking context, so a panel dropped by a
   header control can only win through its ancestor's value.)
6. **Deviation = registration.** A new cue means a new cue-register row
   (an owner decision) before any styling exists.
7. **One renderer per fact type.** A date, a Signatur, a count renders
   through exactly one template filter/include. Divergent spellings of the
   same fact ("Juli 1962" vs "1962-22") are impossible when only one place
   turns the fact into text. (Owner, 2026-08-06 — supersedes the planned
   copy law; the doubling defect class dies with one-implementation-per-view
   plus this rule.)

8. **One height source per control row** (owner correction 2026-08-07).
   Every interactive child of a control row — a toolbar,
   the header — consumes the row's `--control-height` knob. Equal sizing
   must hold BY CONSTRUCTION, never by two components' values happening to
   agree; a per-component height inside a control row is a defect.
9. **Breakpoints are derived, never invented.** Any width threshold that
   hides content cites the content arithmetic it derives from (the sum of
   the columns' min-content widths + gaps), written next to the query. A
   threshold that hides content while space remains is a defect — provable
   computed: at any width where a column is hidden, showing it would
   overflow.
10. **No status-only bands.** A horizontal band exists only with a primary
   occupant; status text (counts) rides an occupied band; a band whose
   occupants are all hidden collapses entirely.
11. **Intrinsic first, queries last** (owner, 2026-08-07: "use a more
   flexible approach using grids and flexboxes" instead of guessing
   breakpoints). Layout adapts through flexible mechanisms as the FIRST
   resort — `minmax()`/`fr` tracks that share space, `flex-wrap`,
   `auto-fit`, content that tightens or truncates. A width query is the
   LAST resort, reserved for genuinely MODAL changes (the phone fold, the
   pane column appearing) — and then it derives per C9. Before writing any
   query, show why no flexible mechanism can absorb the variation.
12. **An overlay positions against its CONTROL ROW, not its trigger**
   (recorded 2026-08-07 from the containment fixes; owner may veto). A
   dropped panel's containing block is the row that owns the trigger (the
   header cluster, a toolbar), so both its edges stay inside that
   row's box and the panel can never leave the viewport — the trigger's own
   viewport offset is not expressible in CSS. Per-trigger anchoring
   (`anchor-scope` + `anchor()` insets + `justify-self: anchor-center`,
   which clamps to the row; never
   `position-area`/`position-try`) rides on
   top as the appendix-F enhancement, never load-bearing. Every overlay is
   covered by the containment walker (section E).

13. **A resting look must lose to every state rule** (owner, 2026-08-08). TWO mechanisms decide that, and which one applies
   depends on whether the default and the state sit in the SAME `@layer`:
   - **Same layer → specificity.** Declare the default inside `:where()`, so it
     carries zero specificity and every state rule (`:hover`,
     `:focus-visible`, `:user-invalid`, `:has(.error)`, `[aria-*]`) outranks it
     without a contest.
   - **Different layers → LAYER ORDER decides, and `:where()` is only
     documentation.** A later layer wins at any specificity, so a default
     restated in a later layer beats the state rule below it even from
     `:where()`. Zero specificity is not the fix there: do not declare the
     property in the later layer at all — consume the component's knob (C3), or
     narrow the selector to what the rule is actually about.

   In source an outranked state rule is indistinguishable from a correct one, so
   this is construction, not review, and both shapes are only findable computed.
14. **A composition styles only the structure it placed** (owner, 2026-08-08). Selectors reach the nodes the composition itself put on the
   page, via direct-child paths (`.karte > section > h2`), never bare
   descendants that can match inside a nested component. The compositions layer
   outranks components, so a descendant selector is a silent override of any
   component that happens to sit inside. This is C4 made enforceable:
   components own the inside.

## Themability law (owner, 2026-08-06)

The design must stay changeable. The lever is the role-token layer, and
only it:

- **Component CSS is mode- and theme-blind.** It consumes role tokens;
  it never knows which mode resolved them. (This is why "no raw hex" is
  law, not taste.)
- **A redesign is a retint of `tokens.css`.** If changing the look requires
  touching component CSS, the token layer has a hole — that hole is the
  defect, fix it there. (The monochrome redesign is the test case: it needs new roles —
  `--ink-3`, `--faint`, `--edge` — and removes others; component CSS changes only where a
  component itself changed.)
- **A mode is a token remap.** Light/dark exist today (`light-dark()` per
  role). A **high-contrast mode** is the planned third: a
  `@media (prefers-contrast: more)` block remapping the same roles (harder
  secondary ink, a stronger edge, thicker lines) — zero component changes.
  Windows forced-colors is respected by not fighting system colors.
- The seed line is gone with the violet world: the monochrome roles carry no hue. A sibling DPB
  service that wants its own colour adds it through the role layer, never in components.

## D. One-line rulings (owner, 2026-08-06)

- **Motion: licensed only to explain a change of size or place** (monochrome amendment,
  2026-09-27; the desk-plane sheet motion retired with the paper material): e.g. the compact
  search field growing on focus (`--motion-grow`). Never decorative or idle, never blocking,
  always honoring `prefers-reduced-motion`. Forbidden verbs: zoom, bounce, ripple, parallax.
- **Icons: permitted; text-first is the current default, not a ban**
  (owner, 2026-08-06). Adopting icons is a register decision: ONE
  consistent set, one register row naming where icons live. Binding part
  regardless of the choice: every icon-only control carries an accessible
  name (a11y floor), and no per-agent ad-hoc icon picks.
- **Viewport targets:** archivist surfaces desktop-first (their real
  workplace); the reader view phone-first (member links arrive via
  chat/mail).
- **A11y floor: WCAG 2.2 AA**, enforced by the axe-core pass riding the
  rework wave.

## E. Lintable subset

The machine-checkable slice of B and C, enforced by
`tests/app/web/test_design_lint.py`:

- no raw hex in component CSS (existing law, restated);
- square corners: no `corner-shape`, no `border-radius` other than `0`;
- no `box-shadow` (row 8 retired, row 12 amended) — except the doubled error edge of row 5
  (`inset 0 0 0 var(--line-width) var(--error)` on `[aria-invalid="true"]`), which the field
  component wave adds to the check's allowlist;
- no `--error` consumption outside row 5's licensed selectors;
- no `margin` on component root selectors;
- bare px/rem literals outside `tokens.css` flagged (comment-exempted per
  C5);
- no compositions-layer selector past a component root (C1);
- a knob is resolved once (C3): a `var(--_x)` needs a `--_x:` in the same section, and a
  public knob with a fallback is read only on a `--_` line (handing it on to another knob is
  setting it).

**Generic computed invariant (mandatory):** one
e2e test walks EVERY control row on the journey pages (each `[role=toolbar]`,
the header's control cluster) and asserts all interactive
children compute the same height and font treatment. Per-instance copies of
this test are forbidden — the walker covers new rows automatically.

What the lint cannot check — composition, alignment, one-fact-one-place —
is the design gate's checklist: catechism questions 2–4 and 6–8, judged on
the state gallery and live pages (the `design-gate` agent, `.claude/agents/design-gate.md`).

## F. Modern CSS baseline (owner, 2026-08-06)

Counterweight to agent training bias toward legacy CSS: the toolkit is
pinned, availability tier follows consequence of failure. The test is
"does the feature's absence break task completion?"

**Availability tiers:**
- **Functional** (absence breaks the task): **Baseline widely available**
  only. Today that includes `@layer`, `:has()`, container (size) queries,
  `<dialog>`, `<details>`, `light-dark()` (newly available until it turns
  widely available, about 2026-11), `color-mix()`/oklch, nesting,
  `:user-invalid`.
  `display: contents` is allowed for layout (owner, 2026-09-29): the layout
  works in every engine; its "limited" status comes only from old a11y bugs.
- **Non-functional / progressive enhancement** (absence degrades
  gracefully): **Baseline newly available** allowed. View transitions
  (degrades to an instant swap),
  `@starting-style` + `transition-behavior: allow-discrete`, `popover`
  (as enhancement over a functional fallback until it turns Baseline widely available in
  October 2026; the monochrome menus rely on it from then), style queries,
  `text-wrap: balance/pretty`.
- **Limited-availability enhancement**: allowed when an `@supports` fallback
  keeps the task working (owner, 2026-09-29) — `field-sizing` (without it the
  field keeps its fixed height and scrolls).
- **Pre-Baseline decoration**: allowed ONLY where the un-supported
  rendering is automatically acceptable with zero fallback code —
  the `corner-shape` precedent (older browsers draw rounded corners,
  accepted). Anchor positioning sits here until Baseline: enhancement
  only, never load-bearing.

**Legacy blacklist** (defects, not style choices): float/clearfix layout;
JS for state `:has()`/`details`/`popover`/CSS can express; `!important`
outside a deliberate `@layer` override; px media queries for component
adaptation where a container query belongs; div-buttons and other
re-implemented native elements (restates construction law).
