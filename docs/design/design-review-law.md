# Design review law

Status: LIVE DOCUMENT (owner-ratified 2026-08-06). The enforceable half of
`design-system.md`: how any UI change is reviewed, which visual cues are
licensed and where, and when to use which styling mechanism. Written to bind
an agent with NO other context — a reviewer gets this file and the code,
nothing else (validated by a blind-agent test run, 2026-08-06).

Rules first, fixes later (owner ruling): existing CSS is *measured* against
this document; bringing it into compliance is the rework wave's job, not a
side effect of a review.

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
| 1 | Bevel cut | Drawer-tab family only: `.c-sig`, `.c-facet-tab` — **single cut, leading (top-left) corner** (owner ruling 2026-08-06). The card's former index cut has no row (`c-card` is an exhibit; if it becomes a citizen its cut is a new owner decision). | forbidden |
| 2 | Violet ink (`--primary`) | `.c-sig-code`; mono counts/dates; inline links (`a` in running content) | forbidden |
| 3 | Inversion (solid fg/bg swap) | selection/active states | forbidden — especially as hover, and never as a tonal tint wash |
| 4 | Amber (`--draft`) | the ENTWURF lifecycle badge | forbidden |
| 5 | Red (`--error`) | errors | forbidden — not for warnings or emphasis |
| 6 | Dashed border | empty/hollow slots (e.g. "ohne Signatur") | forbidden — never decoration |
| 7 | Quiet default | the published/normal state renders no badge | — |

| 8 | Paper sheet material (owner ruling 2026-08-06: "paper material, but not the generic Google Material look") | Sheet-like containers only (result cards, facet panels, confirm panels, empty state): a whisper of seed tint (`color-mix` over `--primary-container`), a hairline cut edge, and EXACTLY ONE depth cue — the 2px lower edge, the thickness of the sheet. This is the papier recipe promoted to baseline; the separate variant file still dies in the wave. | forbidden — and the Material-Design vocabulary is forbidden everywhere: no elevation `box-shadow` stacks, no ripple, no gradients-as-lighting, no textures, no rounded-pill chrome |

**Reserved (recorded, NOT licensed):** trapezoid tab — both top corners cut —
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
- **Icons: text-first.** No icon font, no icon-only buttons; the existing
  marks (✕, arrows) are typography.
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
