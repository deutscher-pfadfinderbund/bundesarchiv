# Bundesarchiv design system

Status: LIVE DOCUMENT (owner, 2026-07-10) — updated as design decisions land;
no formal acceptance step. Governs all web UI from Part 4 on. Sibling DPB
services reuse the whole system by swapping one seed line.

**Enforceable half:** `design-review-law.md` (same directory) — the review
catechism, the cue register (the ONLY licensed visual cues, MAY-only), the
cascade rules, and the lintable subset. Owner-ratified 2026-08-06; reviews
and the design gate run against it.

## Construction law (owner, 2026-08-05)

How UI gets BUILT — these rank with the visual laws below. Background: agents
tend to fill gaps with invented chrome and ad-hoc markup; these rules make
simplicity checkable instead of a matter of taste.

- **Semantic HTML (2026) is the basis.** Native elements and their built-in
  behavior first (`form`, `fieldset`, `dialog`, `details`, `nav`, `table`,
  `output`, …); a div-plus-CSS reconstruction of something HTML already
  provides is a defect. Deviate from browser-plain only where a law here or
  the spec demands it.
- **Composition model, three layers** (owner, 2026-08-06; replaces the
  earlier atoms→molecules→layouts→pages ladder):
  1. **Components** — atoms/molecules (`templates/components/`), semantic
     HTML first. Reuse-first: no ad-hoc one-off markup where a component
     exists, no redundant near-duplicates; anything genuinely new is added
     DELIBERATELY — named, filed, mapped here — or it doesn't ship.
  2. **Views** — self-contained work surfaces (facet panel, result ledger,
     article reader, edit form, confirm panel). Viewport-agnostic: a view
     adapts to its CONTAINER (`@container`), never to the screen. One
     implementation per view — the reader in the workbench pane and on the
     detail page is the SAME view, composed differently.
  3. **Compositions** — arrangements of views per available space, built
     from a small set of reusable CSS layout primitives (Every Layout
     style: Sidebar, Stack, Cover, …). Desktop composes several views;
     narrow shows one at a time with navigation between them.

  **Precedent rule:** a new view copies the nearest approved view and
  changes the minimum. Deviating from precedent needs an owner ruling —
  the approved views are the framework; there is no separate screen spec.

  References: Every Layout (Pickering/Bell — composition primitives),
  CSS container queries (view adaptivity; inside the browser floor),
  Atomic Design (Frost — terminology: view ≈ organism).
- **Provenance.** Every visible element traces to a named archivist wish
  (`docs/requirements/`), an owner ruling, or a spec section
  (`docs/design/part-4-web.md`). No element exists "for completeness."
- **Consistency beats novelty.** The same action looks and behaves the same
  everywhere; one pattern per problem. A second variant of an existing
  pattern needs an owner ruling, not an agent's judgment call.
- **CSS: the cascade, not a class taxonomy** (owner, 2026-08-05; Tailwind
  considered and rejected — no Node build step, and utility soup fights the
  semantic-HTML basis). Style semantic elements in scoped contexts using
  modern native CSS (nesting, `@scope`, `@layer`, `:where()` for
  low-specificity defaults); consistency comes from the custom-property
  tokens (the three layers above), which stay the single source of visual
  truth. Classes only where semantics cannot discriminate, named for
  meaning. The legacy `c-*`/`l-*` prefix taxonomy is DEPRECATED — do not
  extend it; it dissolves in one deliberate rework wave (no piecemeal
  migration: two coexisting class systems is the worst state).
- **UI waves end at the design gate, judged on pixels.** Deliverable is
  before/after gallery renders (`docs/agents/design-gate-brief.md`) for the
  owner's verdict — agent prose about the UI is not acceptance. Subtraction-
  first: prefer waves that only remove.

## Rework-wave charter (owner interview, 2026-08-06)

The one deliberate wave that dissolves the `c-*`/`l-*` taxonomy. Scope
rulings (binding; source: `docs/requirements/owner-interview-2026-08.md`):

1. **Markup may change.** Where a native element replaces a div
   construction, replace it in the same wave (`<dl>` for the Akte
   key/value rows, `<fieldset>`, `<search>`, `<nav>`, …) — the cascade
   must style real semantics, not re-labelled divs. Classes survive only
   where semantics cannot discriminate, named for meaning. The target
   structure is the three-layer composition model above: the taxonomy
   dissolves into components + views + composition primitives, and the
   pane/detail-page duality becomes one reader view in two compositions.
2. **Delete `components-papier.css`** and the components-demo variant
   toggle. One look; the papier experiment is over.
3. **Dissolve bare-element wrapper components** (`button.html`,
   `input.html`, `select.html`) into plain semantic HTML styled by the
   cascade. Structural atoms stay (signatur_tab, facet_group, ledger_row,
   pagination, …).
4. **Demo pages are the storyboard.** `components_demo` / `layouts_demo`
   stay, and every component change updates them in the same wave —
   lockstep is the price of keeping them.
5. **Fold vs column-drop at the gate.** SETTLED (owner verdict 2026-08-07,
   on pixels): column-drop won and is THE width behavior — low-priority
   columns drop as the ledger's container narrows (Typ, then Datierung);
   the two-line fold survives only under the phone-width ~32rem container
   query (kept below the narrowest pane-open container) as the last
   resort. The `?fold` switch, the pane-open fold and the losing CSS are
   gone; row anatomy never changes with pane state.
6. **Tests move in the same wave, and e2e is mandatory.** Some unit/e2e
   selectors grip `c-*`/`l-*` names (`c-badge--entwurf`,
   `c-artikel-aktionen`, `l-zurueck`, …) — migrate them with the markup.
   A cascade rework is exactly the known regression class in `CLAUDE.md`
   (position/overlay rules on `hidden`-gated elements intercepting
   clicks), so the wave's gate is the e2e journeys, not gallery renders
   alone. An axe-core pass over the journey pages rides along (carried
   from issue #9) — the semantic-HTML upgrade is the moment to measure
   and fix the a11y crop.

Success criterion: net-negative diff in CSS lines and unique class names
(169 classes / ~2,344 CSS lines at charter time), zero visual regressions
outside the deliberately changed states, gallery renders as the verdict
medium.

## Principles

- **Roles, not colors.** Components reference role tokens (`--surface`,
  `--on-primary`, …). Only the reference layer mixes color. A hex value in a
  component style is a defect (convention; reviewed at the design gate).
- **The stamp grammar** (owner, 2026-07-10) is the color-application law:
  the seed tint appears ONLY on archival marks — Signatur codes, mono
  counts/dates, links, the focus ring. All other chrome is neutral;
  selection/active/primary states are neutral ink INVERSIONS (swap fg/bg),
  never tint fills. Draft amber and error red are the only loud colors.
  (The "papier" variant may use a whisper of seed tint as sheet MATERIAL on
  surfaces — material, never state.)
- **Every signal carries information, exactly once** (owner, 2026-07-10).
  No labels restating the visible ("SIG" before a Signatur code), no badges
  for default states, no state in titles, no filler chrome. One base
  treatment per element class; differences only as systematic modifiers
  (link affordance on sortable heads, one direction glyph on the active
  sort).
- **Archivist ergonomics rank with the visual laws** (owner, 2026-07-11).
  This is a weekly work tool: keyboard flow matters (tab order = field
  order, Enter submits the primary action, autofocus lands where the work
  starts — Titel on create, Signatur after Kopieren, first error on
  validation), serial workflows (Kopieren cataloging, bulk edit) get the
  fewest possible round-trips, and density stays workbench-compact. A
  design review of archivist screens judges the session, not just the
  pixels.
- **Contrast is a tested invariant.** Every role pair carries a minimum WCAG
  ratio, enforced by a CI test in both modes. The test, not the stylesheet,
  is the source of truth for the numbers (same philosophy as the SQL ≡
  `can_view` equivalence grid).
- **One seed per service.** The archive is violet, desaturated to ink
  (seed chroma ~0.055; neutrals at or near zero chroma). Another DPB service
  changes `--seed` and gets a coherent light+dark palette.
- **Modes follow the OS.** `color-scheme: light dark` + `light-dark()` per
  role. No toggle in v1; adding one later needs no token rework.
- **Modern CSS floor** (owner, 2026-07-09): OKLCH relative colors and
  `light-dark()` require ~2024+ evergreen browsers. No fallback layer.
- **Pfadfinder details are extensions, not structure** (owner, 2026-07-09).
  The system must be complete and shippable with all of them removed.

## Layer 1 — seed

```css
:root {
  color-scheme: light dark;
  --seed: oklch(0.55 0.13 300); /* the ONLY line a sibling service changes */
}
```

## Layer 2 — reference ramps

Derived from the seed with relative color syntax; nothing below this layer
mixes color by hand.

- **Tonal ramp**: `oklch(from var(--seed) <L> c h)` at fixed L steps.
- **Neutral ramp**: `oklch(from var(--seed) <L> 0.012 h)` — near-gray with a
  whisper of the seed hue, so surfaces retint with the service automatically.

## Layer 3 — roles

Each role declares its light and dark value in one place:

```css
--surface: light-dark(
  oklch(from var(--seed) 0.98 0.005 h),
  oklch(from var(--seed) 0.22 0.012 h)
);
```

| Role | Pairs with | Minimum contrast |
|---|---|---|
| `surface` | `on-surface` | 4.5:1 |
| `surface` | `on-surface-variant` | 4.5:1 |
| `surface-container-lowest/low/mid/high` | `on-surface` | 4.5:1 each |
| `primary` | `on-primary` | 4.5:1 |
| `primary-container` | `on-primary-container` | 4.5:1 |
| `draft` (ENTWURF amber) | `on-draft` | 4.5:1 |
| `error` | `on-error` | 4.5:1 |
| `outline` vs adjacent surfaces | — | 3:1 |
| `focus-ring` vs all surfaces | — | 3:1 |

Initial L values are an implementation detail; the table's pairs and
minimums are the contract, judged at the design gate. The four `surface-container`
steps are the elevation ramp (page → panel → card → raised) in both modes.

Semantic notes:

- `draft` exists because lifecycle state (ENTWURF) is core archive vocabulary,
  not a decoration. Published items carry NO lifecycle marker (absence = published,
  since v1 lifecycle is binary); only drafts pop.
- `error` is reserved for Part 4.7 form validation ("Inzwischen geändert",
  field errors). Do not repurpose.

## Non-color tokens

- **Type roles**: `wordmark` (the header's Bundesarchiv mark ONLY — small-caps
  system serif with `--wordmark-tracking`, the one display face with character;
  owner-licensed 2026-08-07, exploration 05 idea (b) — paired with the fine
  double rule under `body > header`), `display` (screen titles), `title` (card
  titles), `body`,
  `meta` (dense controls + secondary cells), `label` (facet headings, column
  heads, badges — letterspaced small caps), `mono` + `mono-meta` (Signaturen,
  Datierungen, counts — tabular). Every text node maps to exactly one role;
  an ad-hoc font-size/weight/case in component CSS is the typographic raw
  hex. New roles enter tokens.css deliberately, never per-component. Faces:
  system stacks in v1; vendored OFL faces are a later, drop-in decision.
- **Spacing**: 4px-base scale (`--space-1` … `--space-8`), density chosen for
  a weekly work tool: compact but not cramped.
- **Shape**: `--radius-s`, `--radius-m`, `--bevel`. Cut corners draw via
  native `corner-shape: bevel` (the index-card cut — the one shape signature,
  used on the Signatur tab, cards and drawer tabs); the browser owns the
  geometry, so borders and fills follow it automatically. Older browsers
  render rounded corners instead — accepted, no fallback (owner, 2026-07-10).

## Layout (owner, 2026-07-10; rail 2026-08-07)

The workbench composes header · **filter rail** · results · preview pane.
The rail is the PRIMARY filter interaction (owner 2026-08-07, exploration
02 verdict — the facet sidebar died with it): one horizontal row directly
under the header holding a native `<details>` dropdown per facet group
(the dropped panels float on the one overlay shadow, register row 12 —
owner 2026-08-07) plus the active filters as inversion
chips (register row 3), each with a labeled remove ✕. The rail itself sits
bare on the desk — no background band, no bottom rule (rail-wave verdict
2026-08-07). Every filter stays a
plain GET link; the rail lives outside `#results`, so filter clicks
re-render it with fresh counts (same mechanism the sidebar used). On
narrow viewports the rail wraps — results are never buried under stacked
panels.

The LEDGER fills the frame (dense register rows drawn as a bound
line-table, exploration 05a: hairline horizontal rules only, no header
band, the row-11 margin rule after the Signatur column, Datierung as a
right-aligned figure column; SIG · Titel · Datierung · Typ · row-action
toolbar; one label-role header treatment; no Sichtbarkeit column —
ÖFFENTLICH renders nothing and the ENTWURF mark rides the title, owner
2026-08-07), preview pane right. Pane state lives in the URL,
server-rendered — zero JS required. Width is the only density input
(2026-08-07 verdict): columns drop as the ledger's container narrows (Typ,
then Datierung); the two-line fold survives only under the phone-width
~32rem container query (kept below the narrowest pane-open container) as
the last resort. Below 1280px the pane disappears and rows navigate to the
detail page (the canonical permalink). Cards remain for photo-heavy and
member-facing contexts.

## Component mapping (workbench)

| Element | Roles |
|---|---|
| Page background | `surface` |
| Header bar | `surface-container-high` |
| Filter rail | bare on the desk (no band, no rule — rail-wave verdict 2026-08-07); dropdown summaries flat hairline buttons; dropped panels `surface-container-lowest`, hairline, floating on `--overlay-shadow` (register row 12) |
| Active facet | inversion (`on-surface`/`surface`) — the dropdown's active row and the rail chip (register row 3) |
| Result card | `surface-container-low`, hover `-mid` |
| Signatur tab | `primary-container` / `on-primary-container`, `mono`, beveled leading corner; no visible microlabel (sr-only "Signatur"); absent `ref_code` → "ohne Signatur" hollow slot (dashed `outline-variant`, no fill), independent of lifecycle. The edit-form header omits the hollow slot — the Signatur input on that screen carries absence (signals-once); the hollow slot stays in the ledger and read view. |
| Chips | inversion (`on-surface`/`surface`) — the rail's active-filter mark (register row 3), labeled remove ✕ |
| Header actions | QUIET (owner 2026-08-07, rail round 2 — Mock B): "Suchen" is the plain hairline button; the create actions live in the ONE "+ Neu …" disclosure (`details.menu`) — quiet hairline summary, panel floating on `--overlay-shadow` (register row 12); "Bestand bearbeiten" joins the panel only while a Bestand filter is active. `.primary` inversion survives on form submits (Anlegen, Speichern, Veröffentlichen, Änderung prüfen) |
| ENTWURF badge | `draft` / `on-draft`; in the ledger it rides the Titel as a quiet amber mono mark (no box — owner 2026-08-07); the boxed badge remains on the reader/edit headers |
| Visibility badge | ledger column died 2026-08-07 (quiet default — no visibility strings in the ledger); the badge component survives only on the publish over-exposure preview |
| Published lifecycle | no marker — absence = published (v1 lifecycle is binary) |
| Focus | `focus-ring`, 2px offset outline |

## Contrast

Contrast for the pairs in the table above is judged at the design gate
(gallery renders every state in both modes). The automated WCAG contrast
test was removed in the 2026-08 test audit — colors are chosen once; the
tokens file is the single place they change, and a change goes through the
design gate anyway.

## Extensions (optional, non-integral)

Each is additive, isolated behind its own class names, removable without
touching the system: Waldläuferzeichen as state language (empty results, 404,
"noch nicht eingeordnet"); Kohte silhouette in the empty state; pennant/trail
geometry for micro-icons (chip ✕, markers). Implement opportunistically,
never at the cost of the core.

## Migration plan

1. `tokens.css` (all three layers). No visual change yet.
2. Restyle the workbench stylesheet to consume roles only; parity-check
   against the approved round-3 mock (dark) and its light-mode derivation.
3. Every later screen (4.7 form, 4.8 collections, 4.6 detail) consumes roles
   from day one; new colors enter via the reference layer or not at all.
