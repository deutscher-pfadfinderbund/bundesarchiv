# Mock design system — brief (2026-09-27)

Owner: `r3-linien/style.css` was never simplified or decomposed and has hardcoded values
throughout. Before any more screens are mocked, turn it into a small, composable system whose
structure mirrors the production CSS, so it can later move into the app almost 1:1.

## Read first

1. `RULES-DRAFT.md` (this folder) — all principles (rule · intention · gain · cost · boundary),
   navigation architecture, space budget (S < 40rem, M, L ≥ 80rem).
2. `r3-linien/` — the baseline: `style.css`, `start.html`, `archiv.html`, `artikel.html`.
3. Production structure to mirror: `src/bundesarchiv/app/web/static/tokens.css` (the `@layer`
   order and `--type-*` / `--space-*` token idiom) and the owned-component law in
   `docs/design/design-review-law.md` section C1 + `docs/requirements/owner-interview-2026-08.md`
   "Component architecture rulings (owner, 2026-09-25)".

## Deliverable (write ONLY in `system/` and `r4-system/` in this folder)

### `system/system.css`, in four layers: `@layer tokens, elements, components, layouts;`

- **tokens** — the only place any raw value lives:
  - color roles (light + dark; dark tuned, not just inverted — keep r3's values);
  - type roles as font shorthands `--type-title`, `--type-heading`, `--type-body`, `--type-meta`,
    `--type-label`, `--type-data` (mono, tabular) — every text node uses exactly one role;
  - spacing scale `--space-1 … --space-n` plus roles `--gap-section`, `--gap-head`, `--pad-row`;
  - `--line` (1px solid rule), `--measure`, `--gutter`.
- **elements** — base styling of plain HTML (body, a, headings, table, input, button).
- **components** — one root class each; the component styles only its own inside; it is tuned
  from outside only through knobs (custom properties, component-scoped names, with a fallback),
  listed in one `/* Knobs: … */` comment line at the top of its section. Components:
  - `topbar` (wordmark · tools: optional compact search, "+ Neu …" menu, Abmelden);
  - `search-field` (large on start; compact-growing in the top bar — one component, a knob);
  - `search-sentence` (archive head: "Suche [field] in … · … · …  + Filter", S behaviour);
  - `register` — ONE row-list component replacing r3's separate `.register`, `.lines`,
    `.later ol` and `.zeit`: label left, figure/date right, line between rows only; knobs for
    a leading column (date) and an optional data bar (Zeitleiste); a quiet "set apart" row
    (Unbekannt);
  - `ledger` (result table, sort heads), `pager`, `facts`, `media`, `crumbs`, `resume`,
    `menu`, `button` (primary / secondary; the dark-gray SSO button as a variant), `mark`,
    `section-head`.
  - Components adapt to their container (`@container`), not the viewport, where their S/M/L
    rendering differs.
- **layouts** — arrangement only, no component internals: `page` (measure, gutter),
  `stack` (sections separated by `--gap-section`), `columns` (pair/trio as one auto-fitting
  grid), `split` (media | facts).

No hex, no raw `rem`/`px`, no font shorthand outside the tokens layer (exceptions: `0`, `1px`
inside `--line`, percentages, `ch` measures inside tokens). Write a throwaway check script
OUTSIDE the repo that greps the components/layouts layers for violations and report its output.

### `system/gallery.html`

Every component in its real states (e.g. register with and without leading date, with bar,
set-apart row; ledger with sorted column and an Entwurf row; pager on first page; menu open;
both search-field sizes), shown in containers at S, M and L widths. Real data from `data.json`.

### `r4-system/start.html`, `archiv.html`, `artikel.html`

The r3 pages rebuilt from `system.css` only (no page CSS file). Proof: screenshot r3 and r4 at
1440×900 and 390×844, light and dark, full page, and compare. List every visible difference and
classify it: bug (fix it) or deliberate simplification (name why — e.g. the merged register).

## Rules

- Keep the r3 look; this is a decomposition, not a redesign. Where r3 was inconsistent (two
  near-identical sizes), unify on one token and list it as a simplification.
- Every visual decision lands in a token or a knob, never twice.
- Screenshots via a throwaway script OUTSIDE the repo, `uv run python` from the repo root, the
  project's Playwright Chromium, into
  `/private/tmp/claude-501/-Users-bjebb-Developer-DPB-archive/8a00aa04-f029-440c-967f-d56c2acc2385/scratchpad/sys/`.
  Mocks are served at `http://127.0.0.1:8765/<folder>/<page>.html`.

## Report

Top-3 difficulties; the token table (roles + values); the component list with knobs; the
difference list (bug / simplification); the check-script output; open questions in plain terms.
