# Design review law

Status: LIVE DOCUMENT (owner-ratified 2026-08-06). The enforceable half of
`design-system.md`: how any UI change is reviewed, which visual cues are
licensed and where, and when to use which styling mechanism. Written to bind
an agent with NO other context — a reviewer gets this file and the code,
nothing else (validated by a blind-agent test run, 2026-08-06).

Rules first, fixes later (owner ruling): existing CSS is *measured* against
this document; bringing it into compliance is the rework wave's job, not a
side effect of a review.

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
| 5 | Red (`--error`) | field errors (`.field-error`); the doubled edge of `[aria-invalid="true"]` controls and of an autocomplete box holding one; the edit-conflict notice (`.record-meta-alert`: its 3px top rule and its subhead); whatever carries the `.danger` context, on hover, press and focus (the × of `.remove` and of a chip, the menu's "Löschen", the delete confirm's button) | forbidden — not for warnings or emphasis |
| 6 | Dashed border | empty / hollow slots (e.g. "ohne Signatur") | forbidden — never decoration |
| 7 | Quiet default | the published / normal state renders no mark | — |
| 8 | Paper sheet material | **RETIRED** (2026-09-27: flat — no tint, no shadow). | forbidden — no shadow, gradient, glow or texture anywhere |
| 9 | Icons | ONE stroke set (24px grid, stroke 2, `currentColor`; app `components/icon.html`, mock `system/icons.svg`, name for name). Slots: row toolbars (`role="toolbar"`, the media row tools), the removing × (`.remove`), the top bar's Abmelden (`log-out`). Every icon-only control names itself. | forbidden — no icon fonts, no second style |
| 10 | Pane-row marker | **SUSPENDED** until the list page is recomposed (the preview pane itself is an open question; its token `--surface-container-high` has no monochrome role). | forbidden |
| 11 | Ledger margin rule | **RETIRED** (2026-09-29, the list wave: the a2 list the owner reviewed has no vertical rule; the Signatur is a quiet column near the end). History: one vertical hairline after the leading Signatur column. | forbidden — no vertical rules |
| 12 | Floating panel edge | **AMENDED** (was the overlay shadow; 2026-09-27 the edge went from `--edge` to `--ink`: a panel is never quieter than the control that opened it): transient panels are page surface with a 1px `--ink` border, in the top layer via the native popover — the menu (`ul.menu[popover]`), the help popover (`.popover`), the tool panel (`.toolpanel`), the suggestion list (`.autocomplete-list`) | forbidden — no shadow on anything |
| 13 | Sort glyph | the direction glyph on the sortable head carrying the active sort; on other sortable heads only on hover / focus (`.ledger th > a`; mock `.ledger-sort`) | forbidden — no step-up of the sorted column |
| 14 | Hairline row rule | `--rule` 1px between the rows of a register or ledger that have two ends (a lead and a figure) | forbidden — never above the first or below the last row, never under headers, filter bars or section heads |
| 15 | Heavy rule | 3px, `--error`: the top of the edit-conflict notice only (`.record-meta-alert`) | forbidden — section rules were removed (`r3-linien`) |
| 16 | Help mark ⓘ | the character U+24D8 at the end of a field hint (`.help`), opening a `.popover` | forbidden — no "?" glyphs, no hover-only tooltips |
| 17 | Note | `.note` (note type, `--ink-3`) touching a label or heading ("intern") | forbidden — never at a far edge, never boxed |
| 18 | Placeholder cross | `--placeholder` in `--faint` on an item without an image (`.media-item`, `.plate-item`, `.file-row-thumb`) | forbidden — no placeholder where no medium is expected |
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
   never past it (owner, 2026-09-25 — `owner-interview-2026-08.md`,
   "Component architecture rulings"; the roots: `design-system.md`,
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
4. **Components own the inside; compositions own the between.** No external
   margins on components. Clearance for a component's own positioned parts
   is internal spacing and comes from the scale like everything else.
5. **Tokens are the only value source.** Spacing from `--space-*`. The
   non-spacing dimensions have named tokens: `--touch-target` (2.75rem),
   `--touch-target-compact` (2rem — the header's row knob;
   owner ruling 2026-08-07, rail round 2), `--line-width` (1px),
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
   header control can only win through its ancestor's value — learning G.36.)
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
   which clamps to the row — see G.50 for why not
   `position-area`/`position-try`) rides on
   top as the appendix-F enhancement, never load-bearing. Every overlay is
   covered by the containment walker (section E, learning G.26).

13. **A resting look must lose to every state rule** (owner, 2026-08-08 —
   learnings G.29, G.47). TWO mechanisms decide that, and which one applies
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
14. **A composition styles only the structure it placed** (owner, 2026-08-08 —
   learning G.30). Selectors reach the nodes the composition itself put on the
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
- no compositions-layer selector past a component root (C1).

**Generic computed invariant (the G.1 pattern, generalized — mandatory):** one
e2e test walks EVERY control row on the journey pages (each `[role=toolbar]`,
the header's control cluster) and asserts all interactive
children compute the same height and font treatment. Per-instance copies of
this test are forbidden — the walker covers new rows automatically.

What the lint cannot check — composition, alignment, one-fact-one-place —
is the design gate's checklist: catechism questions 2–4 and 6–8, judged on
the state gallery and live pages (`docs/agents/design-gate-brief.md`).

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

## G. Learnings register (append-only)

Mechanism (owner, 2026-08-07): every design-gate round that corrects an
agent decision appends its lesson here, GENERALIZED — the rule that would
have prevented the correction, not the anecdote. Reviewers read this
section as part of the law. Never rewrite or delete entries; supersede
with a newer one.

**2026-08-07, workbench composition rounds 1–3:**

1. **A comment is not a proof; the computed style is.** The header CSS
   claimed "ONE treatment for every column head" while the browser computed
   three different sizes (a link inside the header escaped the label rule).
   When a rule claims uniformity, verify it in the browser
   (`getComputedStyle` over the claimed set), not in the source.
2. **Repetition dilutes a mark.** A licensed cue (the Signatur tab
   silhouette) carried into a 50-row ledger stops being a signature and
   becomes chrome. License cues per CONTEXT, and expect scarcity: the more
   often a mark appears on one surface, the quieter it must be.
3. **Sweep each law horizontally.** The quiet-default law was obeyed by one
   atom (lifecycle badge) and violated by its sibling (visibility badge)
   for a year. When reviewing against a law, check every element the law
   touches on the surface — not just the component under review.
4. **Prominence is a frequency claim.** Rank every element by how often the
   surface's primary user needs it; the layout must match that ranking
   (result count and bulk tools are status/occasional — they collapse or
   recede; they never outrank the ledger).
5. **Materials need role assignments, not taste.** "Tinted or not" per
   component drifts; the metaphor assigns roles (desk = neutral ground,
   furniture = quiet, THE pulled sheet = tinted) and every container gets
   styled by its role.
6. **The demo corpus is a design instrument.** "Entwurf Lagerchronik" as a
   test title made every render lie about badge duplication. Corpus data
   must look like real archive content, or verdicts made on renders are
   verdicts about test data.
7. **Decide on renders, not prose.** Every contested composition question
   in these rounds was settled in minutes once both options were rendered
   (live-page CSS/JS injection is cheap); none had been settled by
   description. Mock first, rule second.
8. **Report in the reader's decision language.** A gate brief for the owner
   shows pixels and numbered decisions; internal metrics (class counts,
   line deltas) prove charter compliance to agents and belong in the
   engineering report, not the owner's brief.

**2026-08-07, workbench composition rounds 4–5:**

9. **Slots, not scattered buttons.** Actions live in named, extensible
   toolbar slots (a view's toolbar, a row's action toolbar). A new action
   lands in an existing slot; an agent never invents a new button position.
   Slots are how a layout absorbs growth without recomposition.
10. **Columns serve the scanner; exceptions ride their fact.** A column
   exists only for facts the surface's primary user scans across rows
   (year, type). A rare state (ENTWURF, a future GRUPPE mark) qualifies a
   fact and renders attached to that fact — never a reserved column that is
   empty in the normal case.
11. **Depth is a model, not an effect.** Contact model (sheets resting on
   the desk: one tight contact shadow) vs float model (Material elevation
   ramps) — commit to one; mixing reads amateur. And a lawful cue still
   reads as an accident when it is the only depth in view: assign material
   roles across the WHOLE surface (what is desk, furniture, sheet), then
   apply the cue to every member of the role, not to one.

**2026-08-07, view rulings after the explorations:**

12. **Typography is a role, everywhere — including mocks.** Across agent
   renders the table column headers came out different every time (the
   owner spotted it across the exploration set, after G.1 caught it in
   production CSS). The rule generalizes: every text style names a type
   role from tokens.css — in live CSS, in demo pages, AND in exploration
   mocks; a render whose typography does not come from the roles pollutes
   the judgment made on it. Where uniformity is claimed, prove it computed
   (the G.1 test pattern).

**2026-08-07, session retrospective (owner: "what can structurally help us
for the future?"):**

13. **Blind agents are the measuring instrument for the law itself.** Every
   context-free run (review of facet_group, the pixels-only gallery review,
   the two code reviewers) outperformed context-laden judgment AND returned
   a list of places the law failed to bind — which became the next law
   edits. Institutionalize: run reviews blind, and treat the reviewer's
   "where I had to guess" section as the primary deliverable.
14. **The loop that converges is mock → ruling → law → build.** Four
   composition rounds (v1–v4) settled in hours what prose proposals had
   not settled in weeks: render a cheap variant, get one-line owner
   verdicts, write them into the law, THEN build once. Never build first
   and ask second.
15. **A ruling exists only once it is committed.** Chat is not a record —
   every owner sentence with decision content goes into
   `docs/requirements/` (verbatim where possible) in the same turn it is
   spoken, or it will be re-litigated later.
16. **Label every image REAL or MOCK.** The owner could not tell product
   screenshots from exploration renders — a mock that is not marked as a
   mock quietly becomes a false claim about the product's state. Every
   render shown for judgment carries its provenance: REAL (live app at
   commit X) or MOCK (static/injected, not in the product).

**2026-08-07, rail-wave autopsy (six owner corrections on the first render):**

17. **A new surface class needs an explicit material-role assignment in the
   brief.** The filter rail was new — neither desk, furniture, sheet nor
   overlay had been assigned — so the writer styled it by analogy (a banded
   bar like the header) and it read heavy. Every wave brief names the role
   of every NEW surface before styling starts; row 8's role list is the
   vocabulary.
18. **Constants outlive their reasons.** The Signatur column kept v4's
   track floor and alignment, sized for the tab chrome that no longer
   exists — a reskin re-derives geometry from the new anatomy instead of
   inheriting numbers whose justification died.
19. **Visual weight is relative — after a subtraction wave, re-rank the
   survivors.** The header create buttons were "minor" against the old
   busy surface and "horrid" against the new quiet one. Q9 is a ratio:
   quieting a surface re-ranks everything left on it, so every wave ends
   with a fresh Q9 pass over what it did NOT touch.
20. **Lukewarm acceptances are provisional.** "Still not a fan, but
   acceptable" (the collapsed Sammelbearbeitung) was treated as settled
   law and shipped again unchanged; one wave later the owner tightened it.
   Record lukewarm verdicts as revisit-candidates with the reservation
   quoted, not as closed decisions.

**2026-08-07, round-2 gate corrections (four sibling-consistency escapes):**

21. **Per-instance proofs don't generalize themselves.** The G.1
   computed-style test protected exactly the ledger headers it was written
   for; the header's "+ Neu" summary and the rail chips reintroduced the
   same defect class beside it. Invariants are written as WALKERS over all
   instances (every control row), so new siblings are covered the day they
   appear.
22. **Equality by construction, not by coincidence.** Two components whose
   independent values happen to match will drift; siblings that must match
   consume one shared knob (C8). "This shouldn't even be possible" is a
   demand for construction, not for review vigilance.
23. **A hidden element must be provably out of space.** The column-drop
   thresholds were invented for one composition and hid columns at 680px
   with room to spare. Every content-hiding threshold derives from measured
   content minimums (C9) and carries a computed proof.

**2026-08-07, Opus review of the PR tail (six confirmed findings):**

24. **`max-content` is a hard floor, not a preference.** A bare
   `max-content` track can never shrink, so intrinsic sizing needs
   shrinkable floors (`minmax(floor, max-content)`) wherever content length
   is unbounded — and intrinsic-sizing proofs must run against LONG content
   fixtures, or they pass vacuously on the short demo corpus (the ledger
   overflowed the page body from 800px down with a realistic long
   Signatur).
25. **An enhancement may only hide what it can account for.** The
   progressive-visibility JS counted this page's checkboxes and hid the
   bulk affordance while a URL-borne selection from another page was live —
   stranding the archivist. Client logic that overrides server-rendered
   state must incorporate every state source the server used (URL params,
   not just DOM), and htmx history restores need their own re-init hook.
26. **Overlays need viewport-containment proofs.** Both new floating panels
   (header menu, rail dropdowns) could leave the viewport (clipped labels,
   document horizontal scroll) at widths no gallery state rendered. Every
   overlay gets a computed containment check across the width range — as a
   generic walker, per G.21.

**2026-08-07, session retrospective round 2 (owner: "what did we learn?"):**

27. **Owner corrections arrive as instances but live as classes.** Every
   round of point-by-point feedback in this session collapsed into ONE
   structural hole: four "different" defects were one sibling-consistency
   gap; six were one missing material-role assignment plus one relativity
   effect. Treat a correction list as a class hunt — fix the class, add the
   structural guard, then re-check the whole surface for other instances.
   Fixing the N listed items and stopping guarantees round N+1.
28. **A register that only grows stops being read.** These learnings are
   the ARCHIVE; section H is the working memory. Every new learning that
   implies a pre-return action must also land as a checklist line, or it
   will be true, recorded, and ignored.

**2026-08-08, form-wave exploration (three bugs in my own mock, one class):**

29. **A resting look declared at high specificity swallows every state beneath
   it.** The card's default ("value on a ruled line, no border") outranked the
   `:has(.error)` rule in a lower layer, so an invalid Datierung rendered with a
   normal border — the red border was in the stylesheet and invisible on screen.
   Same leak muted the error message's ink. Declare defaults inside `:where()`
   (zero specificity) so hover/focus/error always win. Proposed as cascade rule
   C13 (owner decision pending, `docs/design/form-wave-brief.md`).
30. **A composition may only style the structure it owns.** `.karte h2`
   restyled a nested conflict panel's own heading, because the compositions
   layer outranks components. Scope to the nodes the composition placed
   (`.karte > section > h2`). This is C4 with teeth — components own the inside,
   so a composition must not select descendants it did not place. Proposed as
   C14. The same slip in flex form: a row idiom (`flex: 1 1 14rem`) inherited by
   a column container stretched every field to 14rem of HEIGHT.
31. **Field width is a claim about content length — derive it like a
   breakpoint.** C9 already forbids invented width thresholds; one level down,
   an input's width is the same kind of claim. Size fields in `ch` from the
   domain fact (Signatur ≤ 8 characters → 12ch), never from whatever the column
   happened to be. Uniform full-width inputs are what wasted half of a 1440px
   desk on the old form.

**2026-08-08, Opus review of the form wave (eleven ranked findings, nine confirmed):**

32. **An enhancement's swap selector must resolve WHERE IT FIRES.** The shared header
   kept `hx-target="#results"` on five screens that have no `#results`, so htmx
   cancelled the native submit and aborted with `htmx:targetError` — searching
   from the edit/create screens did nothing, silently, because a targetError is
   not a request failure and no error banner shows. Same class one level down:
   htmx INHERITS `hx-select`, so a form's whole-region selector reached the two
   little GET enhancements inside it, htmx selected nothing out of their
   `<option>`/`<span>` responses and swapped exactly that in. Declare an
   enhancement on the region it swaps (then it exists exactly where its target
   exists, by construction), or stop inheritance at the boundary — never leave a
   selector that resolves on one page and not on its siblings.
33. **A fold may hide no MESSAGE and no FOCUS, not just no data.** "Folded rare
   sections with their values in the summary" was obeyed for values and violated
   for everything else: a validation error re-rendered inside a shut `<details>`
   is invisible, and `autofocus` inside one focuses nothing at all. Decide
   `[open]` server-side from the SAME error/autofocus context the fields render
   with, declare once which fields each fold holds, and mark the summary from the
   section's own contents (`:has(.error)`) so no flag can disagree with reality.
34. **A permanent fact may not live behind a disclosure — and a test that must
   OPEN one to see a fact is reporting the defect.** The exposure statement was
   what let the publish gate retire, yet below the pane's switch it sat inside a
   shut fold: on a narrow window it was on screen nowhere, and the e2e proof
   clicked the fold open and passed. When a gate is deleted on the strength of a
   promise, the guard for that promise may not contain a workaround.
35. **An action that navigates away from a form must carry the form.** Putting
   Veröffentlichen in the same row as Speichern made it a save-shaped affordance;
   posting it as its own transition rebuilt the record from disk and discarded
   every unsaved edit. Either the action rides the form's single write, or it is
   not allowed to sit in the form's action row.
36. **On-viewport is not reachable.** Both overlay panels sat perfectly inside
   the viewport while an opaque sticky row painted over them and ate every click.
   A containment proof answers a geometry question; reachability needs
   `elementFromPoint` — and a stacking-order fix needs a CLICK, because
   Playwright's own actionability retry will happily scroll a merely-awkward
   element into reach. Extend the check for every overlay, never for the one that
   failed.
37. **A guard keyed by a non-unique name silently narrows itself.** The C8 walker
   keyed rows by a generated name; every ledger row toolbar produces the same one
   (`span[toolbar]`), so all but the last collapsed in the dict and the walk
   proved ONE row while reporting green. Walkers key by POSITION, and their test
   asserts a minimum count of what the page composes — a shrinking guard is worse
   than a missing one.
38. **`initial` on a custom property is not a value.** It is the
   guaranteed-invalid value, so every consumer falls back to its OWN default: one
   knob resolved to `--touch-target` for one rule and `auto` for another, and the
   comment was true of only half of it. To say "not the row's height, the full
   touch target here", RE-DECLARE the knob. Sub-floor hit areas hid behind this
   (23px facet entries under the AA 24px floor).
39. **Derive a sticky offset from the chrome above it — and prove the sticky
   works at all.** The sheet's offset was a guessed constant against a 49px row;
   deriving it exposed that `position: sticky` had never done anything, because
   the pane column was only as tall as its own content and the declaration had no
   slack to work in. Dead styling reads exactly like live styling in source.

**2026-08-08, four-angle cleanup review of the form wave (twenty findings, one
refuted):**

40. **A guard's SET must be derived, or the walker only protects what someone
   remembered to type.** G.21 made invariants walkers over all instances; one
   level up, the instances are SCREENS, and four hand-maintained page lists (the
   gallery's states, the axe paths, the overlay walker's pages, three URLs in the
   C8 test) had already drifted from the app in the same direction: only the
   PUBLISHED record has media, so the wave's new media-register toolbar was
   composed on a screen none of the guards loaded. One inventory, every guard
   derives its view of it, each screen NAMES the minimum it must compose so a
   no-find cannot pass as a green walk.
41. **A lint cannot exempt what it cannot see.** The px/rem rule never inspected
   at-rule CONDITIONS — a width threshold, the most consequential literal a
   stylesheet holds — and never checked that the file list it lints is the file
   list on disk. Both are the same defect: a check whose SCOPE is asserted rather
   than derived. Every value rule runs over at-rule conditions; the stylesheet
   list is gated against the glob.
42. **Equality by coincidence hides best where the code is right for the wrong
   reason.** The reader's sheet hand-picked fields off the stored Article instead
   of the domain's projection, and printed identical bytes because the floored
   field set happens not to intersect what the sheet shows — on the very surface
   whose promise retired the publish gate. When a value must come from a
   pipeline, CALL the pipeline; "the output matches today" is the G.22 argument
   in a new costume.
43. **A retired gate takes its affordance, never its FAIL-CLOSED branch.** The
   preview panel blocked publishing whenever exposure could not be computed,
   because the confirm checkbox lived inside the branch that rendered the
   statement. Replacing the panel with permanent chrome kept the promise and
   dropped the teeth: no statement rendered, and Veröffentlichen stayed one click
   away. When a gate is deleted, enumerate its branches — the ones that REFUSED
   are the ones a replacement forgets.
44. **A complement is a second source unless one condition states both sides.**
   The in-card exposure statement hid on WIDTH while the sheet replacing it needs
   width AND a body class, so a card without the class lost the fact entirely.
   Express the switch once, in the file that owns it, and let the DEFAULTS be the
   other side — a negated query is a copy that has to be kept true by hand.
45. **A knob a component cannot know it owns is a patch waiting to happen.**
   `[role=toolbar]` set the ROW height knob; inside a control row the row owns it,
   so the row had to undo the toolbar with a per-instance `inherit`. A component
   declares its own FALLBACK and consumes the row's knob — then "inside a row" and
   "standing alone" are the same code.
46. **Two spellings of one fact need two renderers, not five call sites.** C7 is
   satisfied by one implementation per SPELLING: the machine date and the human
   date are both licensed, and each now has exactly one renderer. (This review
   asked for the sheet's machine date to become human German; the preview pane —
   the reader surface the sheet reuses, sharing its `.meta` hook and its CSS rule
   — prints the machine value, so the sheet was right and the request was
   refuted. A finding against a shipped reader surface has to name that surface.)

**2026-08-08, mutation audit of the cleanup wave (each invariant broken on purpose):**

47. **`:where()` cannot save a rule that is in the wrong LAYER.** Deleting the
   `:where()` from the card's resting rule left the error border RED — the border was
   delivered by layer order (compositions > components), not by zero specificity — while
   RESTATING `border-color` inside the compositions layer broke it, `:where()` or not.
   Same mechanism one layer up: a components-layer ink rule for a toolbar's children
   reached the pane's `a.button`, whose look lives in the elements layer, and won from
   inside `:where()` — 14.98:1 down to 2.24:1. So C13's `:where()` is the SAME-LAYER
   mechanism; across layers the only fix is not to declare the property in the outer
   layer. A `:where()` in the wrong layer reads like a guarantee and is a comment.
48. **A rule your linter ships DISABLED is a check you do not have — and
   enabling it is only half.** The vendored axe ships `target-size` off by
   default, so a "WCAG 2.2 AA pass" selected by tag ran no target-size check at
   all for months. Enabling it was still unfailable: axe returns the
   sub-24px-and-too-close case as `incomplete`, and a result class nobody reads
   is a result class nobody has. Audit the tool's defaults, then audit which of
   its result classes your assertion actually counts.
49. **A guard whose expectation is derived from the thing under test is a
   tautology that reports green.** The first CAS-diff guard read its expected row
   list off `_FIELDS` — the registry it existed to protect — so deleting a field
   deleted the expectation with it. Where a guard defends a declaration, its
   expectation is written out verbatim (the German rows, the screen count), even
   though duplication is normally the defect. Derive the SET under test; never
   derive what it is compared against.

**2026-08-22, overlay panels over their own trigger (issue #53, owner priority #1):**

50. **`@supports` proves parsing, not behavior — an enhancement needs a computed
   proof of its own PROMISE in the gate browser.** The anchored tier matched its
   `@supports`, then landed both panels over their own trigger: the pinned
   Chromium (149) resolves `position-area` against the row instead of the anchor
   even in the minimal two-sibling case, and `position-try` fallbacks can never
   engage for a panel that by design escapes its row's block end (no try option
   ever "fits", so the base placement silently sticks). The containment walker
   asserted viewport edges and hit-testability but never "panel below its
   trigger", so the broken tier pre-empted a correct fallback for weeks. Two
   rules: an enhancement's defining behavior gets its own walker fact (here:
   panel top ≥ trigger bottom), and prefer the anchor primitives whose result is
   provable per-element (`anchor()` insets, `justify-self: anchor-center`) over
   the composite properties whose failure mode is a silent wrong position.

**2026-09-27, monochrome system and the a1 review:**

51. **A 1px red edge does not stand out from a gray edge.** The error edge read as "just another
   frame" in light mode; red and gray at one pixel differ in hue more than in weight. The error
   state doubles the edge (border plus a 1px inset shadow) so weight carries it, not hue alone.
52. **`:where()` zeroes only what it wraps.** `.tools :where(button):hover:enabled` still counts
   two pseudo-classes and outranked the red hover of the × it meant to stay below. Wrap the
   whole compound (`:where(button:hover:enabled)`) when a default must lose to a component.
53. **A part that restates an inherited value breaks in the next context.** The "*" marker and
   the help mark carried their own colour and size; inside a hint or a quieter label they stood
   out wrong. Rule "Inherit first" (design-system.md principles): a part sets only what differs,
   and the elements layer resets form controls to inherit once.
54. **A dark theme needs its own "inactive" colour.** The hairline that is right for connecting
   rows (~1.35:1) made disabled arrows and placeholder crosses vanish on black. Present-but-
   inactive things get `--faint`, tuned brighter in dark than the hairline.

Run before returning from ANY UI wave. Ten lines distilled from the
learnings register (section G is the archive and the reasoning; this is the
operational form — learning G.28).

1. **Walkers green:** control-row heights (C8 — rows keyed by POSITION, and the
   test asserts the MINIMUM count of rows the page composes, G.37), overlay
   containment AND hit-testability (G.26/G.36), header uniformity (G.1) — plus
   the design lint (E). Not "should pass": run them.
2. **Every new surface is page or band** and floats only as a native popover with an edge
   (register row 12). (Monochrome amendment; the desk / furniture / sheet roles of G.17 retired.)
3. **Every distinctive cue cites a register row** (B) — including its
   position. No row, no cue.
4. **No invented numbers:** width queries derive from measured content and
   carry the arithmetic plus a computed proof that hiding was necessary
   (C9); flexible mechanisms were tried first (C11).
5. **Siblings that must match consume ONE knob** (C8). Two independent
   values that agree today are a defect, not a pass.
6. **Re-rank what you did NOT touch:** subtraction changes relative visual
   weight, so re-run Q9 over the whole surface (G.19).
7. **Fixtures are realistic** (domain facts, not invented extremes), and
   stress tests target the genuinely unbounded fields (G.6, G.24) — a proof
   over short demo data proves nothing.
8. **Client logic accounts for every state source the server used** (URL
   params, not just DOM) and survives an htmx history restore (G.25).
9. **Docs, demo pages and comments in lockstep**, and every uniformity
   claim is proven computed rather than asserted in prose (G.1).
10. **Report labels every image REAL or MOCK** (G.16), and names lukewarm
   owner acceptances as revisit candidates rather than settled law (G.20).
11. **Defaults in `:where()`; selectors scoped to what you placed.** Every
    resting look must still lose to hover/focus/error (G.29), and no selector may
    reach into a nested component's own parts (G.30). Check the LAYER, not only the
    specificity: across layers `:where()` decides nothing, so a property restated in a
    later layer wins anyway (C13, G.47). Verify on the STATE renders — in source, an
    outranked state rule looks identical to a correct one.
12. **Every enhancement's target resolves on every screen it ships to** (G.32) —
    including inherited `hx-*` selectors — and no fold hides a message, the
    focus, or a permanent fact (G.33/G.34). If a guard has to open a fold or
    click something extra to see a fact, the fact is not where it belongs.
13. **No dead styling and no guessed offsets:** a sticky/positioned declaration
    is proven to MOVE something, and any clearance derives from the box it must
    clear, through one knob both sides consume (G.39, C5/C9). A custom property
    is never `initial` when a value is meant (G.38).

14. **Every guard's SET is derived, not typed** (G.40/G.41): screens come from the
    one inventory (`tests/e2e/_pages.py`), stylesheets from the glob, rows and
    fields from the registry that declares them. If you added a screen, a
    stylesheet or a field and had to edit a second list by hand, that second list
    is the defect.
15. **A value that must come from a pipeline CALLS the pipeline** (G.42), and a
    deleted gate's refusing branches are enumerated before the gate goes (G.43).
    "The output matches today" is never the argument.

16. **A guard you edited is a guard you must break on purpose** (G.48/G.49). A
    wave that touches a walker, a lint rule, an inventory or a drift guard ends
    with a mutation pass: violate each invariant, watch each guard go red,
    revert. Twice a guard here narrowed silently and kept reporting green; the
    only thing that caught it was breaking the code underneath it. Check the
    tool's disabled defaults and which result classes you count, and check that
    no expectation is derived from the thing under test.

**Enforcement caveat (owner, 2026-08-08: CI stays off for now):** none of the
guards above run on a push — CI is not active (issue #12). "Green" means an
agent ran it and said so in its report, which makes line 16 the only thing
standing between a narrowed guard and a false green.
