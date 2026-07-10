# Bundesarchiv design system

Status: LIVE DOCUMENT (owner, 2026-07-10) — updated as design decisions land;
no formal acceptance step. Governs all web UI from Part 4 on. Sibling DPB
services reuse the whole system by swapping one seed line.

## Principles

- **Roles, not colors.** Components reference role tokens (`--surface`,
  `--on-primary`, …). Only the reference layer mixes color. A hex value in a
  component style is a defect (pinned by the raw-color sweep test).
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

Initial L values are an implementation detail pinned by the contrast test;
the table's pairs and minimums are the contract. The four `surface-container`
steps are the elevation ramp (page → panel → card → raised) in both modes.

Semantic notes:

- `draft` exists because lifecycle state (ENTWURF) is core archive vocabulary,
  not a decoration. Published items carry NO lifecycle marker (absence = published,
  since v1 lifecycle is binary); only drafts pop.
- `error` is reserved for Part 4.7 form validation ("Inzwischen geändert",
  field errors). Do not repurpose.

## Non-color tokens

- **Type roles**: `display` (wordmark), `title` (card titles), `body`,
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

## Layout (owner, 2026-07-10)

The workbench is **split-narrow**: sticky collapsible facet sidebar left
(native `<details>` groups), LEDGER results center (dense register rows:
SIG · Titel · Datierung · Typ · Sichtbarkeit · row action; one label-role
header treatment), preview pane right. Pane state lives in the URL,
server-rendered — zero JS required. While the pane is open the ledger folds
to two-line narrow rows (the mail-client fold); below 1280px the pane
disappears and rows navigate to the detail page (the canonical permalink).
Cards remain for photo-heavy and member-facing contexts.

## Component mapping (workbench)

| Element | Roles |
|---|---|
| Page background | `surface` |
| Header bar | `surface-container-high` |
| Facet group panels | `surface-container-low`, headings `label`/`on-surface-variant` |
| Active facet | `primary-container` / `on-primary-container` |
| Result card | `surface-container-low`, hover `-mid` |
| Signatur tab | `primary-container` / `on-primary-container`, `mono`, beveled leading corner; no visible microlabel (sr-only "Signatur"); absent `ref_code` → "ohne Signatur" hollow slot (dashed `outline-variant`, no fill), independent of lifecycle |
| Chips | `primary-container` / `on-primary-container` |
| Primary actions (Suchen, Neuer Artikel) | `primary` / `on-primary` |
| ENTWURF badge | `draft` / `on-draft`; the Sichtbarkeit value for drafts (shown instead of the visibility badge) |
| Visibility badge (published, archivist only) | `outline` + `on-surface-variant` |
| Published lifecycle | no marker — absence = published (v1 lifecycle is binary) |
| Focus | `focus-ring`, 2px offset outline |

## Contrast test

`tests/app/web/test_design_tokens.py`: parses `tokens.css`, resolves every
role to sRGB for both modes (small color-math helper or a dev-only
dependency), computes WCAG ratios for every pair in the table above, fails
under the stated minimum. Gates run it like any other test.

## Extensions (optional, non-integral)

Each is additive, isolated behind its own class names, removable without
touching the system: Waldläuferzeichen as state language (empty results, 404,
"noch nicht eingeordnet"); Kohte silhouette in the empty state; pennant/trail
geometry for micro-icons (chip ✕, markers). Implement opportunistically,
never at the cost of the core.

## Migration plan

1. `tokens.css` (all three layers) + contrast test. No visual change yet.
2. Restyle the workbench stylesheet to consume roles only; parity-check
   against the approved round-3 mock (dark) and its light-mode derivation.
3. Every later screen (4.7 form, 4.8 collections, 4.6 detail) consumes roles
   from day one; new colors enter via the reference layer or not at all.
