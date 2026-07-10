# Archivist wishes 2025 — mapping to the new system

Source: "Überarbeitung Homepage 2025" (baron, henkel, veilchen; Stand
2025-10-21) — the working archivists' requests against the OLD system,
mapped onto the new build. The PDF stays outside the repo (contains
contact-person workflow details); this file is the durable extract.

## Solved by architecture — no action

| Wish | How it is solved |
|---|---|
| Signatur sorts alphanumerically (BA 2 before BA 10, not "computernumerisch") | ICU collation `de_numeric` in the index (ADR 0011) |
| Trunkierung: `Lied*` finds Liederbuch, Liedgut, … | Prefix search (ADR 0011); UI supports a trailing `*` |
| Datum as YYYY / YYYY-MM / YYYY-MM-DD, sortable | EDTF dates, sortable via `date_earliest/latest` |
| Attachment limit (old: max 3 files, zip workaround) | `media` tuple is unbounded and ordered |
| Member catalog search broken (subcategories, "Felder leeren") | Workbench replaces it wholesale |

## Feeds Part 4.7 (cataloging form) — binding input

- **View first, edit deliberately.** Items open read-only (the 4.6 detail
  view); editing is an explicit route. Matches their overwrite-protection
  ask; the concurrent half is already CAS (ADR 0013).
- **"Item kopieren"** action: duplicate an article **with the Signatur
  cleared** (they specified exactly that) so the archivist must assign a
  new one.
- **Medienart → Dokumenttyp as dependent vocabulary** — Dokumenttyp must
  not be limited to Schrifttum, and newly added types must show up in
  filters and sorting.
- **Media reorder controls** (order = meaning; first = cover, ADR 0015)
  plus per-file caption inputs (ADR 0015).
- Delete disabled while in edit mode (their button-state model) — fold
  into the form's action layout.

## v1 backlog (owner, 2026-07-10: "bulk edit on day 1")

- **Bulk edit**: select rows in the ledger, change ONE field across all
  selected. Their field list: Standort, Autor, Ort, Medienart, Dokumenttyp,
  Quelle, Sammlungsteil (= Collection), Querverweis, Besitzer. Slots in
  right after 4.7 (reuses the form's field widgets + per-article
  `save_article` CAS + sync reindex). The ledger layout carries the
  selection column.
- **Papierkorb** (their softened overwrite ask): restore accidentally
  deleted/overwritten items. Files-canonical makes a trash feasible;
  needs its own small design (where deleted trees park, retention).

## Post-v1 (owner, 2026-07-10: "inbox can stay later")

- **Digitale Eingangskiste** (member upload inbox) — full spec exists in
  the PDF: Medienart-first tailored forms; per-type formats and quality
  asks (images ≥300 dpi jpg/png, text PDF/A searchable, audio mp3, video
  mp4/avi); Pflichtfelder Titel + Kontaktperson (→ Quelle); consent
  checkbox; up to 3 related files per mask; session prefill for serial
  uploads; admin e-mail notification; entries land as "noch nicht
  bearbeitet" (maps to a `submitted` lifecycle state), invisible to
  members until approved. Their own sequencing note agrees: upload only
  after member search works (duplicate check first).

## Old-system field vocabulary (migration mapping, Part 7)

Autor → creator · Ort → subject_place / Ort der Veröffentlichung ·
Standort → physical_location (archivist-only) · Sammlungsteil →
Collection · BA-Nummer → ref_code (physical counterpart reference) ·
Quelle / Querverweis / Besitzer / Anmerkungen → custom bag (graduation
candidates later).
