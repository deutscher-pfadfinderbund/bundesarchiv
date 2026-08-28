---
name: Bundesarchiv
description: The DPB archive workbench — cut paper sheets on a gray desk, marked in stamp-ink violet.
colors:
  # Light-mode resolutions of the role tokens. NORMATIVE SOURCE: src/bundesarchiv/app/web/static/tokens.css
  # (seed → ramps → roles, each role a light-dark() pair). Dark values + canonical
  # definitions live in .impeccable/design.json colorMeta. Change colors there, never here.
  surface: "oklch(0.98 0 300)"
  surface-container-lowest: "oklch(0.96 0 300)"
  surface-container-low: "oklch(0.94 0 300)"
  surface-container-mid: "oklch(0.92 0 300)"
  surface-container-high: "oklch(0.90 0 300)"
  on-surface: "oklch(0.25 0 300)"
  on-surface-variant: "oklch(0.46 0 300)"
  primary: "oklch(0.45 0.05 300)"
  on-primary: "oklch(0.99 0 300)"
  primary-container: "oklch(0.92 0.022 300)"
  on-primary-container: "oklch(0.32 0.045 300)"
  draft: "oklch(0.90 0.10 85)"
  on-draft: "oklch(0.42 0.11 72)"
  error: "oklch(0.52 0.20 27)"
  on-error: "oklch(0.99 0 300)"
  outline: "oklch(0.50 0 300)"
  outline-variant: "oklch(0.84 0 300)"
  focus-ring: "oklch(0.50 0.055 300)"
typography:
  wordmark:
    fontFamily: "ui-serif, Iowan Old Style, Charter, Georgia, Times New Roman, serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.12em"
    fontFeature: "small-caps"
  display:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.02em"
  mono:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.4
  mono-meta:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "0.78rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  s: "4px"
  m: "6px"
  bevel: "12px"
spacing:
  "1": "0.25rem"
  "2": "0.5rem"
  "3": "0.75rem"
  "4": "1rem"
  "5": "1.25rem"
  "6": "1.5rem"
  "7": "1.75rem"
  "8": "2rem"
components:
  button-quiet:
    backgroundColor: "{colors.surface-container-low}"
    textColor: "{colors.on-surface}"
    typography: "{typography.meta}"
    rounded: "{rounded.s}"
    padding: "0.25rem 0.75rem"
  button-quiet-hover:
    backgroundColor: "{colors.surface-container-high}"
  button-primary:
    backgroundColor: "{colors.on-surface}"
    textColor: "{colors.surface}"
    typography: "{typography.meta}"
    rounded: "{rounded.s}"
    padding: "0.25rem 0.75rem"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.on-error}"
    typography: "{typography.meta}"
    rounded: "{rounded.s}"
    padding: "0.25rem 0.75rem"
  chip:
    backgroundColor: "{colors.on-surface}"
    textColor: "{colors.surface}"
    typography: "{typography.meta}"
    rounded: "{rounded.s}"
    height: "2rem"
  input:
    backgroundColor: "{colors.surface-container-lowest}"
    textColor: "{colors.on-surface}"
    typography: "{typography.meta}"
    rounded: "{rounded.s}"
    padding: "0.25rem 0.5rem"
  badge:
    textColor: "{colors.on-surface-variant}"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    padding: "0.125rem 0.5rem"
  badge-entwurf:
    backgroundColor: "{colors.draft}"
    textColor: "{colors.on-draft}"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    padding: "0.125rem 0.5rem"
  sig-tab:
    backgroundColor: "{colors.surface-container-low}"
    textColor: "{colors.primary}"
    typography: "{typography.mono}"
    rounded: "6px 0 0 0"
    padding: "0.25rem 0.5rem 0.25rem 0.75rem"
---

# Design System: Bundesarchiv

> Portable digest of the incumbent system. The enforceable law is
> `docs/design/design-review-law.md` (cue register, cascade rules) with
> `docs/design/design-system.md` (principles, construction law); the token
> source is `tokens.css`. Where this file and those disagree, those win.

## Overview

**Creative North Star: "The Archivist's Desk"**

Every screen is a scene of physical archive objects on a gray desk. A new
element must answer "what is this on the desk?" — a cut paper sheet, a bound
register, a drawer tab, a stamp mark. The chrome is hueless paper: pure-gray
surfaces, hairline edges, no decoration. Color is information, applied like
ink: the desaturated stamp violet appears only on archival marks (Signatur
codes, dates, counts, links, focus), draft amber and error red are the only
loud voices, and everything else signals through neutral ink inversions.

This is a weekly work tool for volunteer archivists, not a showcase: density
is workbench-compact, keyboard flow ranks with the visual laws, and
simplicity is an owner requirement — waves remove complexity before adding
capability. The system is seed-parametric: one `--seed` line retints the
whole light+dark palette for a sibling DPB service.

**Key Characteristics:**
- Hueless paper chrome (chroma-0 neutrals); hue only on archival marks
- Flat furniture: hairline borders, exactly two shadow tokens, no elevation ramps
- Bound-register density: ruled rows, tabular mono figures, quiet hover reveals
- Semantic HTML styled by the cascade (`@layer`), tokens as the single visual truth
- German UI text, system font stacks, OS-following light/dark — no toggle

## Colors

A stamp pad on gray paper: one desaturated violet ink, two fixed-hue semantic
voices, and a pure-gray neutral ramp — nothing else.

### Primary
- **Stamp-Ink Violet** (`--primary`, light `oklch(0.45 0.05 300)`): the
  archival ink. Licensed only on marks — Signatur codes, mono dates/counts,
  links, the focus ring, title hover. Never a fill for chrome, buttons, or
  states. Derived from the seed `oklch(0.52 0.055 300)`; chroma deliberately
  pulled to 0.055 so it reads as ink, not paint.
- **Violet Sheet Tint** (`--primary-container`, light `oklch(0.92 0.022 300)`):
  the Signatur tab's paper and the whisper-tint mixed into true sheets.

### Semantic
- **Draft Amber** (`--draft`/`--on-draft`): the ENTWURF lifecycle mark — the
  one amber in the system. Published renders nothing (absence = published).
- **Error Red** (`--error`/`--on-error`): form validation and the one
  `button.danger` on confirm surfaces. Both hues are fixed by design — they
  do not retint with the seed.

### Neutral
- **Paper grays** (`--surface` 0.98 → `--surface-container-high` 0.90, light):
  page → panel → card → raised, all chroma 0. The hued-marks-vs-hueless-chrome
  divide is the system's backbone.
- **Ink grays** (`--on-surface` 0.25, `--on-surface-variant` 0.46): primary
  and secondary text ink; `--on-surface-disabled` fades toward the surface.
- **Hairlines** (`--outline` 0.50, `--outline-variant` 0.84): control edges
  and the darker rules that bind the register.

### Named Rules
**The Stamp Grammar Rule.** Seed tint appears only on archival marks.
Selection, active, and primary states are neutral ink inversions (swap
fg/bg), never tint fills. Draft amber and error red are the only loud colors.

**The One-Line-Swap Rule.** A sibling service changes exactly one line — the
seed — and inherits a coherent light+dark palette. Nothing below the ramp
layer mixes color by hand; a hex in component CSS is a defect.

## Typography

**Display Font:** system-ui stack (working sans)
**Body Font:** system-ui stack
**Mono Font:** ui-monospace stack (Signaturen, Datierungen, counts — tabular)
**Wordmark Font:** ui-serif stack, small-caps — the header's "Bundesarchiv" mark only

**Character:** plain working sans everywhere, tabular mono for archival
figures, and exactly one face with character: the Kapitälchen-serif wordmark.
Labels read mixed case at a hair of tracking (0.02em) — the letterspaced
uppercase label voice retired system-wide (owner 2026-08-22/28).

### Hierarchy
- **Wordmark** (600, 1.5rem/1.2, 0.12em tracking, small-caps serif): header mark only.
- **Display** (600, 1.35rem/1.2): screen titles.
- **Title** (600, 1.05rem/1.35): card and reader titles.
- **Body** (400, 0.95rem/1.5): running text, ledger titles.
- **Meta** (400, 0.85rem/1.4): dense controls, buttons, secondary cells.
- **Label** (600, 0.72rem/1.3, 0.02em, mixed case): facet headings, column heads, badges.
- **Mono / Mono-meta** (400, 0.85 / 0.78rem, tabular-nums): Signaturen, dates, counts.

### Named Rules
**The One Role Rule.** Every text node maps to exactly one type role
(`font: var(--type-*)`). An ad-hoc font-size, weight, or case in component
CSS is the typographic raw hex. New roles enter tokens.css deliberately.

## Layout

The workbench composes header · filter rail · results ledger · preview pane.
Views are self-contained work surfaces that adapt to their **container**
(`@container`), never the viewport; compositions arrange views per available
space. Below 1280px (80rem) the pane disappears and rows navigate to the
detail page.

- **Control rows** (header, filter rail, toolbars): a row sets one
  `--control-height` knob (2.75rem, compact 2rem) and every control on the
  line consumes it — equal heights hold by construction.
- **Intrinsic first:** mono columns sit at max-content over floor knobs, the
  unbounded Titel absorbs slack and ellipsizes first; no invented
  breakpoints. The one width query is the phone-width ~32rem container fold,
  derived arithmetically from the track floors.
- **Spacing:** 4px-base scale (`--space-1` … `--space-8`), workbench-compact.
- **Stacking:** the named z-scale (overlay-panel 2 < control-row 4 < header 5
  < banner 10); a bare z-index is a defect.

## Elevation & Depth

Flat by conviction. Resting surfaces are paper on the desk: hairline edges,
no fills, no elevation ramps, no shadow stacks. Depth exists in exactly two
tokens:

### Shadow Vocabulary
- **Resting contact** (`--sheet-shadow`: `0 1px 2px` low-alpha ink): true
  sheets only — the pulled preview sheet, confirm panels, the empty state —
  the way a sheet resting on a desk touches it.
- **Overlay** (`--overlay-shadow`: `0 2px 8px` low-alpha ink): transient
  floating panels only — rail dropdowns, the "+ Neu …" create menu.

### Named Rules
**The Furniture-vs-Sheet Rule.** Facet panels and control chrome are
furniture: flat, hairline-edged, shadowless. Only true sheets carry the
seed-tinted material (`--sheet`) and the contact shadow. Only transient
overlays float.

## Shapes

Cut paper, not pebbles: small radii (4px controls, 6px cards) and the house
signature — the index-card **bevel cut** via native `corner-shape: bevel`
(12px) on the leading (top-left) corner, licensed for the drawer-tab family
only (Signatur tab, facet tab). Trapezoid double-cuts are reserved, not
licensed. Older browsers render rounded corners instead — accepted, no
fallback. Absence renders as a hollow slot: dashed `--outline-variant`
border, no fill ("ohne Signatur", empty state).

## Components

### Buttons
- **Shape:** 4px radius, hairline `--outline` border, meta type.
- **Quiet (default):** `surface-container-low` fill, hover `-high`. "Suchen",
  toolbar actions, the "+ Neu …" disclosure summary share one declaration set.
- **Primary:** neutral ink inversion (`on-surface` bg / `surface` text) —
  form submits only (Anlegen, Speichern, Veröffentlichen). Not violet.
- **Danger:** `error`/`on-error` fill — the one destructive variant, confirm
  surfaces only.
- **Link buttons** (`button.link`): read as inline text in stamp ink.

### Chips
- **Style:** the active-filter mark — full ink inversion, meta type, compact
  2rem hit height from the rail's knob, labeled remove ✕ inside.
- **State:** a chip *is* the active state; no unselected variant exists.

### Inputs / Fields
- **Style:** `surface-container-lowest` fill, hairline border, 4px radius;
  labels above in label type via `.field`.
- **Focus:** 2px `--focus-ring` outline at 2px offset (global invariant)
  plus border deepening to `on-surface`.
- **Error:** `.error` message node's presence turns the field border red.
- **File input stays native** (German browser renders German strings).

### Badges
- **Default:** hairline outline, label type, transparent — quiet.
- **ENTWURF:** the one amber mark. Boxed on reader/edit headers; in the
  ledger it rides the Titel as a quiet unboxed amber mono mark.

### Signatur Tab (signature component)
The article reader header's mark: mono stamp-ink code on `primary-container`
paper with the beveled leading corner. Everywhere else the same include
renders as plain violet-ink mono code — repetition dilutes a mark. Absent
`ref_code` → dashed hollow slot, "ohne Signatur".

### Ledger (signature component)
The results register as a bound book: hairline horizontal rules only, no
header band, no zebra, no side chrome; the one vertical rule closes the
Signatur column. Five subgrid tracks (bulk · SIG · Titel · Datierung · Typ ·
toolbar). Row hover reveals the action toolbar and bulk checkboxes
(pointer devices; touch keeps them visible); the checked checkbox is the
selection mark. The current row carries the one fill
(`surface-container-high`). Titel hover = link ink + underline; no
persistent link styling.

### Facet Dropdowns
Native `<details>` on the filter rail: flat hairline summary (furniture),
dropped `<ul>` panel floating on `--overlay-shadow`, positioned against the
control row (not the trigger; anchor positioning is a progressive
enhancement). One open at a time; active row marked by inversion via
`aria-current`.

### Pagination
Plain prev/next links; the current page stands in tabular mono ink.

## Do's and Don'ts

### Do:
- **Do** reference role tokens only; new colors enter via the ramp layer or not at all.
- **Do** reach for native semantic HTML first (`details`, `dialog`, `fieldset`, `output`, …); style it with the cascade in the declared `@layer` order (tokens < elements < components < compositions < modes).
- **Do** copy the nearest approved view and change the minimum (the precedent rule); one pattern per problem.
- **Do** let every signal carry information exactly once — no labels restating the visible, no badges for default states.
- **Do** size controls from the row's `--control-height` knob and adapt views with container queries over intrinsic track floors.
- **Do** trace every visible element to an archivist wish, an owner ruling, or a spec section.

### Don't:
- **Don't** put a hex, ad-hoc font-size, bare px dimension, or bare z-index in component CSS — tokens are the single visual truth.
- **Don't** use seed violet as a fill or state color; states invert neutral ink. Amber is ENTWURF's, red is validation's — do not repurpose.
- **Don't** add shadows beyond the two tokens — no elevation ramps, no ripple, no gradients-as-lighting, no textures.
- **Don't** extend the deprecated `c-*`/`l-*` class taxonomy; classes only where semantics cannot discriminate, named for meaning.
- **Don't** un-hide `[hidden]` via display rules (the one sanctioned `!important` enforces it); JS reveals by removing the attribute.
- **Don't** invent chrome "for completeness" — the system must ship complete with every Pfadfinder extension removed.
