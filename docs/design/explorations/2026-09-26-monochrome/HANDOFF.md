# Handoff — UI/UX direction work (sessions 2026-09-26/27)

Resume point for a fresh context. Read this first, then the files it points to.

## Where we are

The owner is redesigning the look and page composition before the edit-form recompose. The work
happens in static mocks under this folder, reviewed element by element with the owner. Nothing
of the new look is in the Django app yet.

| Step | State |
| --- | --- |
| Rulings recorded | `docs/requirements/owner-interview-2026-08.md` — sections "Look, navigation and design-rule rulings (owner, 2026-09-26)" + its navigation bullet (2026-09-27) |
| Rules | `RULES-DRAFT.md` — principles table (rule · intention · gain · cost · boundary), navigation architecture, space budget, live-review rulings |
| Method | `SCREEN-JOBS.md` — job table per screen, cost/gain per element |
| Mock design system | `system/system.css` (layers tokens · elements · components · layouts) + `system/gallery.html`; pages rebuilt on it in `r4-system/` |
| Archivist screens | being mocked by three writers — see "In flight" below |
| Production build | not started |

## Folder map

- `x1-* x2-* x3-*` — round 1 (all monochrome, too similar). Door page = **x3-register/door.html** (ruled).
- `r2-*` — round 2 (structurally different): owner picked **A = r2-druckschwarz** for start/list,
  **C = r2-schaufenster** for the article page.
- `r3-linien/` — A under the line rule; archive page with the search-sentence head; navigation
  architecture applied. Superseded by r4 as the base.
- `system/`, `r4-system/` — the current base (commit `0c66866`).
- `a1-formular/`, `a2-sammel/`, `a3-artikel/` — archivist screens (in flight).
- Briefs: `BRIEF.md` (rounds 1–2), `SYSTEM-BRIEF.md`, `ARCHIVIST-BRIEF.md`.
- Screenshots are NOT committed (`.git/info/exclude`); throwaway scripts live in the session
  scratchpad. Mocks are served by a local `python3 -m http.server 8765` from this folder (restart
  it if needed).

## Key owner decisions (short; the requirements doc is authoritative)

- Keep the small-caps serif wordmark and the hairline table. No scout costume. Adults interested
  in the Bund's history; a functional tool first. Archivists are the most important users.
- Monochrome; no gray chrome, no violet; light first, dark tuned (not only inverted).
- Counts never at display size. No role labels, no redundant marks, no off-topic actions.
- Lines connect row ends, never separate; alignment and spacing give structure; frames only for
  cohesion where no natural line exists (or an input's edge). No dashes. No mono capitals as a
  label voice; mono only for data in columns. Serif only for the wordmark, section headings and
  article titles.
- Price every element AND every fix. Don't signal what the user already knows (sorting: the
  arrow suffices; no column step-up). Hide a control only if it can never become active here
  (Zurück/Weiter stay, disabled).
- Navigation: destinations = start, one list, article, forms, door. Everything else is a preset
  of the one list. Top bar = wordmark · "+ Neu …" (archivists) · Abmelden. Breadcrumbs show the
  place. Compact header search that grows on focus, on article pages.
- Archive head = search sentence: "Suche [field] in Gruppen des DPB · alle Jahrzehnte · jeder
  Typ  + Filter" (max three primary filters; S: one filter + "Filter").
- Start page = composition of presets: search · "Weiter bearbeiten" line (archivists) ·
  Bestände · Nach Art · Zeitleiste (L) · Zuletzt hinzugefügt · later Highlights (curated pinned
  articles, not now). Phone start = search + "Weiter bearbeiten" only.
- Article page = C (media left, facts right) when a square preview exists; PDFs/scans get their
  first page rendered as preview (needs thumbnail generation — owner's UI-pass item 1); else one
  column.
- Edit form: E1 order (Kerndaten → Beschreibung → Einordnung → Herkunft → Medien → Zugriff →
  Weitere Angaben), all open; the Titel field is the page heading. Brief: `WAVE-R.local.md`.

## Status 2026-09-27 (day)

- The owner reviewed a1 live in five rounds (rulings in `REVIEW-ARCHIVIST.md`, "Owner rulings on
  a1, round 1–5") and approved the look: **formalized** as `DESIGN.md` (north star "Druckschwarz"),
  `.impeccable/design.json`, the rewritten `docs/design/design-system.md` and the monochrome cue
  register in `docs/design/design-review-law.md`. `RULES-DRAFT.md` is superseded.
- New system parts from the review: `icons.svg` + `icon`, `autocomplete.js` + `autocomplete`,
  `menu` as native popover, `note`, `title-field`, tokens `--ink-3`, `--faint`, `--placeholder`,
  `--type-note`.
- App changes merged on local main: `added_at` from legacy `pub_date` (c73185d), Schlagworte one
  per line (3683adf). The owner re-imports.
- Open for the owner: `role="button"` on the upload label; Status + Sichtbarkeit as one control;
  versions screens (and restore); a2/a3 not yet reviewed live.
- Next (owner order): retoken + top bar + door in the app.

## Status at handoff (2026-09-27, overnight)

- **All archivist screens are mocked** on the system: `a1-formular/` (bearbeiten, bearbeiten-konflikt,
  neu), `a2-sammel/` (liste, liste-auswahl, pruefen, pruefen-fehler, ergebnis), `a3-artikel/`
  (artikel, artikel-video, artikel-entwurf, loeschen, bestand-neu, bestand-bearbeiten).
  Each folder's `NOTES.md` holds the writer's job tables and per-element pricing, plus
  "Proposed system additions" (not yet merged into `system/`).
- **My overnight review:** `REVIEW-ARCHIVIST.md` — element tables per screen, what I changed and
  why, system changes made, and **18 open questions** for the owner (plain terms).
- **What I learned:** `LEARNINGS.md` — part 1 from the owner's teaching, part 2 from the reviews.
  The owner asked to read this.
- System changes made during the review: `--type-subhead` + `--section-head-type`, `--h1-type`
  (split sides use the heading role), no mono for single fact values, `--measure-prose`,
  `--edge` (control edge ≥3:1, separate from `--rule`), register lines only on two-ended rows.
- Next for the owner, in order: read `LEARNINGS.md`; walk the archivist screens live with
  `REVIEW-ARCHIVIST.md` open; answer the open questions; then decide which "Proposed system
  additions" join `system/` (plate, field, button-danger, bulkbar, chooser, affected, ledger
  pick/act cells, prose, row/column/cluster layouts).

## Owner-ordered plan after the mocks

1. Owner reviews the archivist mocks (element by element, cost/gain) — design all archivist
   screens before any build.
2. Write the rules into the design law (`docs/design/design-system.md` contents + DESIGN.md);
   the mechanisms of `design-review-law.md` stay.
3. Monochrome retoken + top bar + door page in the app; components per the system (one writer
   each, Wave C's owned-component model); then start, list, article pages; then the edit-form
   recompose (`WAVE-R.local.md`, run after the rules).

## Open questions for the owner

- L size: the page content never exceeds ~74rem, so the L (≥ 80rem container) rendering never
  triggers. Lower the L threshold, grow the measure, or judge L on the viewport?
- Navigation targets beyond presets: does a Bestand ever need its own page with its own content?
- "Zuletzt hinzugefügt" needs a date-added field and a visible sort; hidden while every date is
  the import date.
