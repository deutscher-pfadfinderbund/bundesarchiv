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
| 12 | Overlay shadow (owner 2026-08-07: the popover "should have a shadow or something to differentiate it from the background") | TRANSIENT floating panels only — the filter rail's dropdown panels AND the header's "+ Neu …" create-menu panel (`details.menu > ul` — owner 2026-08-07 rail round 2, Mock B: the panel's material role is OVERLAY, per G.17) (`--overlay-shadow`: one soft layer, larger blur than the sheet's contact shadow, low-alpha ink over roles). An overlay genuinely floats; a resting sheet does not — the two shadows stay distinct tokens. | forbidden — still no elevation ramps/stacks on resting surfaces |

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
   `--touch-target-compact` (2rem — the filter-rail chips + their ✕ only;
   owner ruling 2026-08-07, rail round 2), `--hairline` (1px),
   `--state-border` (3px). A dimension used once,
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

8. **One height source per control row** (owner correction 2026-08-07).
   Every interactive child of a control row — a toolbar, the filter rail,
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
   filter rail, the header cluster), so both its edges stay inside that
   row's box and the panel can never leave the viewport — the trigger's own
   viewport offset is not expressible in CSS. Per-trigger anchoring
   (`anchor-scope` + `position-area` + `position-try-fallbacks`) rides on
   top as the appendix-F enhancement, never load-bearing. Every overlay is
   covered by the containment walker (section E, learning G.26).

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

**Generic computed invariant (the G.1 pattern, generalized — mandatory):** one
e2e test walks EVERY control row on the journey pages (each `[role=toolbar]`,
the filter rail, the header's control cluster) and asserts all interactive
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

## H. Writer pre-flight checklist

Run before returning from ANY UI wave. Ten lines distilled from the
learnings register (section G is the archive and the reasoning; this is the
operational form — learning G.28).

1. **Walkers green:** control-row heights (C8), overlay containment (G.26),
   header uniformity (G.1) — plus the design lint (E). Not "should pass":
   run them.
2. **Every new surface has a material role** (desk / furniture / sheet /
   overlay) named in the code and consistent with register row 8 (G.17).
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

**Enforcement caveat:** none of the guards above run on a push — CI is not
active (issue #12). Until it is, "green" means an agent ran it and said so
in its report.
