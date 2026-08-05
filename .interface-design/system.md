# Bundesarchiv — interface-design system notes

Distilled from `docs/design/design-system.md` (the law, live document) for the
interface-design skill. On conflict, the law wins.

## Who / what / feel

Working archivists cataloging weekly; members browsing later. Dense work tool,
not a brochure: compact, quiet, register-like. Feel: an archival workbench —
ink on paper stock, stamped marks, no decoration.

## Non-negotiable laws

- **Stamp grammar**: seed violet appears ONLY on archival marks — Signatur
  codes, mono data (dates, counts), links, focus ring. All other chrome is
  neutral. Selection/active/primary = neutral ink INVERSION (swap fg/bg),
  never tint fills. Draft amber + error red are the only loud colors.
- **Signals-once**: every signal carries information exactly once. No labels
  restating the visible, no badges for default states (published = no marker),
  no filler chrome.
- **No motion**: no transitions/animations — this tool is used 100×/day.
  Busy states are static (e.g. opacity dim).
- **Roles, not colors**: components reference role tokens only; a raw hex in
  component CSS is a defect. Contrast is checked by eye at the design gate
  (gallery renders both modes).
- **Modern CSS floor**: OKLCH relative colors, `light-dark()`,
  `corner-shape: bevel`. No fallbacks.

## Tokens (src/bundesarchiv/app/web/static/tokens.css)

- Seed: `--seed: oklch(0.55 0.13 300)` — the ONLY line a sibling service
  changes. Neutral ramp chroma ≈ 0.012; modes via `light-dark()`.
- Roles: `surface`, `surface-container-lowest/low/mid/high`, `on-surface`,
  `on-surface-variant`, `primary(-container)`, `draft`, `error`, `outline`,
  `outline-variant`, `focus-ring`.
- Type roles (every text node maps to exactly one): `display`, `title`,
  `body`, `meta`, `label` (letterspaced small caps), `mono`, `mono-meta`
  (tabular — Signaturen, Datierungen, counts).
- Spacing: 4px scale `--space-1..8`, workbench-compact density.
- Shape: `--radius-s/m`, `--bevel`; bevel cut only on card index-corner and
  Signatur-tab leading corner.

## Layout

Workbench = split-narrow: sticky collapsible facet sidebar (native
`<details>`), ledger register center (SIG · Titel · Datierung · Typ ·
Sichtbarkeit · action; headers are the sort control), preview pane right via
`?artikel=<ulid>` — server-rendered, zero-JS baseline; HTMX/JS only enhances.
Pane open → ledger folds two-line narrow. <1280px pane hidden, rows link to
detail page. ≤720px single column, children span `1 / -1`.

## Component reality

Atoms in `src/bundesarchiv/app/web/templates/components/` (button, input,
ledger, ledger_row, …) — REUSE FIRST; demo at `/_dev/components/`.
Styles: `components.css` (atoms) + `layouts.css` (frames). Signatur tab =
`primary-container` + mono + beveled leading corner; absent ref_code =
hollow dashed slot "ohne Signatur". ENTWURF badge = draft amber, shown as
the Sichtbarkeit value for drafts only.

## Language

UI German — plain and modern ("Findbuch" banned). Dev-facing English.
