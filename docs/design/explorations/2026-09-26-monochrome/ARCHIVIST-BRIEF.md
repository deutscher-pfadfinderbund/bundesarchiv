# Archivist screens — mock brief (2026-09-27)

Owner goal: design every archivist screen under the new rules before any real build. Archivists
are the most important users. Static HTML mocks, German UI text, English comments.

## Read first (binding, in this order)

1. `RULES-DRAFT.md` (this folder) — the principles table (rule · intention · gain · cost ·
   boundary), navigation architecture, space budget, live-review rulings. Where a rule's
   boundary applies, say so in your notes.
2. `SCREEN-JOBS.md` — the method. Before building a screen, write its job table (who, what they
   try to achieve, success) and price every element (cost vs gain). Put the tables in your
   `NOTES.md`. Also price your fixes: a fix is a new element with its own cost.
3. `docs/requirements/owner-interview-2026-08.md` — owner rulings. Especially: "Edit-form critique
   (2026-08-29)", "Edit-form mock-gate verdicts + Signatur ruling", "Look, navigation and
   design-rule rulings (2026-09-26)" and its navigation bullet. Named voice patterns in
   `docs/design/design-system.md` ("Consequence disclosure", "Conflict is not an error").
4. The real templates in `src/bundesarchiv/app/web/templates/workbench/` for the screen you mock:
   they are the source of the real fields, states, German strings and actions. Do not invent
   fields or actions; do not drop real ones without pricing them in NOTES.
5. The system: `system/system.css` (tokens · elements · components · layouts) and
   `system/gallery.html` (every component in its states). The baseline pages built from it:
   `r4-system/` (`start.html`, `archiv.html`, `artikel.html`).

## Shared visual contract

- **Compose only from `../system/system.css`.** Link it; add NO page stylesheet by default.
  If a screen needs something the system lacks, first check whether an existing component with
  a knob covers it. If not, write a MINIMAL new component in `<folder>.css`, following the
  system's own rules (one root class, knobs with a `/* Knobs: … */` line, tokens only — no hex,
  no raw rem/px, no font shorthand) and list it in NOTES under "Proposed system additions" with
  its job and why no existing component fits. Never edit `system/` or other folders.
- Copy the top bar markup from `r4-system/archiv.html` verbatim. The compact growing search only
  on article-type pages.
- Tokens only — the names defined in `system.css`'s tokens layer (color roles, `--type-*`,
  `--space-*`, gap roles, `--line`). No new colors or sizes. Light first; dark must work via the
  tokens.
- Lines connect row ends; spacing and alignment give structure; frames only for cohesion where no
  natural line exists or as an input's edge. No dashes, no mono capitals as labels, no role
  labels ("nur Archivare"), no redundant marks, no display-size counts.
- Serif: section headings and article titles only. Mono: only data in columns (Datierung,
  Signatur). Everything else sans.
- Real data: `data.json` (this folder). Label anything you mark for the mock (e.g. an Entwurf).
- Three sizes (S < 40rem, M, L ≥ 80rem): archivists work on L; S must still work without
  horizontal scroll, filters folded.

## Deliverable

Your folder only. Pages as listed in your task, your CSS file, `NOTES.md` (screen-job tables,
cost/gain per element, rules whose boundary you hit, open questions for the owner — plain
product terms, self-contained). Screenshots: throwaway script OUTSIDE the repo (your scratchpad),
1440×900 and 390×844, light and dark, full page, saved to
`/private/tmp/claude-501/-Users-bjebb-Developer-DPB-archive/8a00aa04-f029-440c-967f-d56c2acc2385/scratchpad/arch/<folder>/`.
The mocks are served at `http://127.0.0.1:8765/<folder>/<page>.html`. Use the project's
Playwright Chromium via `uv run python` from the repo root. One fix batch, one re-shoot, stop.

Final report: files, the NOTES.md open questions verbatim, screenshot paths. Concise.
