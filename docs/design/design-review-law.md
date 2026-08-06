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

## D. Lintable subset

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
