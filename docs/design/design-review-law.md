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

| # | Cue | Licensed selectors + position | Everywhere else |
|---|-----|-------------------------------|-----------------|
| 1 | Bevel cut | `.c-sig` only — single cut, leading (top-left) corner (owner 2026-08-06). Licensed CONTEXT (2026-08-07, scarcity — learning G.2): the article reader header (detail page and pane), NOT ledger rows — there the Signatur renders as plain violet-ink mono (row 2). `.c-facet-tab` no longer exists in live markup. | forbidden |
| 2 | Violet ink (`--primary`) | `.c-sig-code`; mono counts/dates; inline links (`a` in running content) | forbidden |
| 3 | Inversion (solid fg/bg swap) | the active filter mark — the facet sidebar's active row, and the filter rail's active chip once the rail lands (rail = primary filter interaction). Ledger bulk selection is NO LONGER an inversion — the checked box is the mark, unchecked boxes reveal on row hover/focus (both owner 2026-08-07) | forbidden — especially as hover, and never as a tonal tint wash |
| 4 | Amber (`--draft`) | the ENTWURF lifecycle badge | forbidden |
| 5 | Red (`--error`) | errors; AND the one destructive-action button on a confirm surface (`button.danger` — owner ruling 2026-08-07: "destructive actions can be red") | forbidden — not for warnings or emphasis |
| 6 | Dashed border | empty/hollow slots (e.g. "ohne Signatur") | forbidden — never decoration |
| 7 | Quiet default | the published/normal state renders no badge | — |
| 8 | Paper sheet material (owner rulings 2026-08-06/07: "paper material, but not the generic Google Material look"; "a sheet resting on a desk has a shadow — professionally, a touch of skeuomorphism") | TRUE SHEETS only — the preview pane (the pulled sheet), confirm panels, the empty state: a whisper of seed tint (`color-mix` over `--primary-container`), a hairline cut edge, and EXACTLY ONE depth cue — the RESTING-CONTACT shadow (`--sheet-shadow`: single layer, 1–2px y-offset, blur ≤ 3px, low-alpha ink derived from roles; supersedes the 2px lower edge). Facet panels are FURNITURE, not sheets — flat, hairline only (2026-08-07 role reassignment). | forbidden — and the Material float model is forbidden everywhere: no elevation shadow ramps/stacks, no ripple, no gradients-as-lighting, no textures, no rounded-pill chrome |
| 9 | Icons (owner 2026-08-07) | ONE vendored set of hairline-stroke inline SVGs (24px grid, stroke-width 2 — matches the hairline/ink aesthetic). Licensed slots: the ledger row-action toolbar and view toolbars (`role="toolbar"`). Every icon-only control carries an accessible name. New glyphs join the one set deliberately (demo page in lockstep); no second style, no icon fonts, no ad-hoc picks. | forbidden |
| 10 | Pane-row marker (owner 2026-08-07) | `.ledger [role="row"][aria-current]`: a quiet persistent neutral highlight (`--surface-container-high`) on the one row whose article the pane shows — deliberately NOT an inversion (a previewed row is not a selected row) | forbidden |
| 11 | Ledger margin rule (owner endorsement of exploration 05 idea (a), 2026-08-07) | ONE vertical hairline after the Signatur column of the ledger — the bound-register margin line. | forbidden — no other vertical rules in the ledger |

| 12 | Overlay shadow (owner 2026-08-07: the popover "should have a shadow or something to differentiate it from the background") | TRANSIENT floating panels only — the filter rail's dropdown panels (`--overlay-shadow`: one soft layer, larger blur than the sheet's contact shadow, low-alpha ink over roles). An overlay genuinely floats; a resting sheet does not — the two shadows stay distinct tokens. | forbidden — still no elevation ramps/stacks on resting surfaces |

**Reserved (recorded, NOT licensed):** a serif READING type role (`--type-reading`) for the Lesesaal member composition (owner liked exploration 04's serif reader, 2026-08-07) — licensed when that wave is approved. Also reserved: trapezoid tab — both top corners cut —
for a future register-tab component used as **view navigation** (owner,
2026-08-06). Gets its own row if and when that component is approved; until
then two-cut bevels are forbidden like any unregistered cue.

## C. Cascade rules — when to use which styling

1. **Elements first.** Semantic HTML is styled via element + context
   selectors. A class exists only where semantics cannot express the
   distinction.
2. **Context over variants.** A component adapts to where it sits (ancestor
   scope, `@container`), never via variant modifier classes. **State
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
   `--hairline` (1px), `--state-border` (3px). A dimension used once,
   structurally, may be a literal **with a comment naming why no token
   fits**; a bare literal is an S3 defect.
6. **Deviation = registration.** A new cue means a new cue-register row
   (an owner decision) before any styling exists.
7. **One renderer per fact type.** A date, a Signatur, a count renders
   through exactly one template filter/include. Divergent spellings of the
   same fact ("Juli 1962" vs "1962-22") are impossible when only one place
   turns the fact into text. (Owner, 2026-08-06 — supersedes the planned
   copy law; the doubling defect class dies with one-implementation-per-view
   plus this rule.)

## Themability law (owner, 2026-08-06)

The design must stay changeable. The lever is the role-token layer, and
only it:

- **Component CSS is mode- and theme-blind.** It consumes role tokens;
  it never knows which mode resolved them. (This is why "no raw hex" is
  law, not taste.)
- **A redesign is a retint of `tokens.css`.** If changing the look requires
  touching component CSS, the token layer has a hole — that hole is the
  defect, fix it there.
- **A mode is a token remap.** Light/dark exist today (`light-dark()` per
  role). A **high-contrast mode** is the planned third: a
  `@media (prefers-contrast: more)` block remapping the same roles (harder
  ink, no sheet tint, thicker `--hairline`) — zero component changes.
  Windows forced-colors is respected by not fighting system colors.
- Sibling DPB services retheme by swapping the one seed line (existing law,
  restated — same lever).

## D. One-line rulings (owner, 2026-08-06)

- **Motion: licensed, desk-plane only.** Motion may explain a spatial change
  — a sheet slides in/out on the desk plane (translate + settle), the way
  paper moves on a desk. It need not be "realistic" paper; it must carry the
  feeling. Never decorative or idle, never blocking, always honoring
  `prefers-reduced-motion`. Forbidden verbs: zoom, bounce, ripple, parallax.
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

The machine-checkable slice of B and C, to become a design-lint test in the
rework wave:

- no raw hex in component CSS (existing law, restated);
- no `corner-shape` outside register row 1's selectors;
- no `--primary` / `--draft` / `--error` consumption outside rows 2/4/5's
  licensed selectors;
- no `margin` on component root selectors;
- bare px/rem literals outside `tokens.css` flagged (comment-exempted per
  C5).

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
  `<dialog>`, `<details>`, `light-dark()`, `color-mix()`/oklch, nesting,
  `:user-invalid`.
- **Non-functional / progressive enhancement** (absence degrades
  gracefully): **Baseline newly available** allowed. View transitions
  (the desk-plane motion mechanism — degrades to an instant swap),
  `@starting-style` + `transition-behavior: allow-discrete`, `popover`
  (as enhancement over a functional fallback), style queries,
  `field-sizing`, `text-wrap: balance/pretty`.
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
