# Overnight review of the archivist screens (2026-09-27)

Method (owner): for every element — what is its use, what does it gain, what does it cost — and
price every fix too. The writers' own job tables and per-element pricing are in each folder's
`NOTES.md`; this file records **my** review on top of them: what I found, what I changed, and
what I left for the owner. Pages: `http://127.0.0.1:8765/<folder>/<page>.html`.

## a3-artikel — article page (archivist view), delete, Bestand forms

| Element | Use | Gain | Cost | Verdict |
| --- | --- | --- | --- | --- |
| Square preview + page thumbnails (C layout) | the thing itself | highest | half the width | keep |
| Crumb "Bund" | where the article lives, a way onward | mid | low | keep |
| Fact "Bestand: Bund" | — | none: the crumb already says it and links | a row | **cut** (one fact, one place) |
| Title at page-title size in the side column | name the thing | high | a 3rem serif in a ~35rem column wrapped to four lines and pushed the facts down | **fixed**: a title inside a split side takes the heading role (`--h1-type` knob, set by the layout) |
| Beschreibung with a "Beschreibung" label after the facts | the human story of the object | high | the label restates what prose shows; placed after reference facts it is read last | **moved before the facts, label cut** (`prose` component) |
| Datierung / Signatur in mono inside facts | — | none: a single value is not a column | a third voice | **fixed**: mono only where values align in a column (`.facts :is(time, data)` inherits) |
| Onward sections "Mehr aus …" at section-heading size | continue browsing | mid | as loud as the main content; wrapped to two lines without media | **fixed**: new `--type-subhead` role + `--section-head-type` knob — rank follows gain |
| "Dateien" heading for one file | — | low | section weight for one line | subhead (same fix) |
| Entwurf: quiet mark + "Nach Veröffentlichung sichtbar für: …" | the archivist knows members can't see it yet, and who will | high | low | keep |
| Delete: Signatur far right of the title | identify the article | mid | an eye jump across the page | **fixed**: quiet mono right after the title (Signatur presence budget: "identification only") |
| Delete: red button naming "Artikel und 5 Dateien löschen" | consequence disclosure | high | the one sanctioned red | keep |
| Bestand rename: "Verschieben und Sichtbarkeit ändern folgen später." | — | none for the archivist | development narration in the UI | **cut** |
| Plate gap too large at L | — | — | layout bug | **fixed** (`align-content: start`) |

## a2-sammel — archivist list, bulk check, result

| Element | Use | Gain | Cost | Verdict |
| --- | --- | --- | --- | --- |
| Checkboxes in the gutter, revealed on hover until one is ticked | select rows | high | none while hidden; titles stay aligned with the head | keep (writer's judgment) |
| Selected rows not inverted; the ticked box is the signal | — | one signal | — | keep |
| Sticky bulk bar as one sentence ("3 ausgewählt · … — Standort auf [Wert] setzen — Änderung prüfen") | the bulk action in reach | high | covers rows while scrolling | keep; its top line is legitimate — content passes under it |
| Check page: "→ new value" repeated in bold on every row | — | none after the first row: in a one-field bulk edit the new value is the same for all | three bold identical lines | **fixed**: the new value once in the lede; rows show what each record *loses* ("Standort bisher (wird ersetzt)"). Deviates from the named pattern's literal "{alt} → {neu} per row" — see open questions |
| Commit button "3 Standorte überschreiben" | names the consequence | high | — | keep |
| Result heading "Sammelbearbeitung teilweise abgeschlossen" (two lines) + a count line | — | low | a two-line headline saying little, plus the count in a second place | **fixed**: heading "1 von 3 gespeichert"; count line cut |
| "Diesen Artikel bearbeiten" on every row | — | the same words repeated | noise | **fixed**: the title is the link |
| "Zurück zur Suche" on the result | — | mid: after a POST flow browser Back lands on the check page | — | keep (the "Back restores the search" rule stops at form flows) |

## a1-formular — edit form, conflict, new article

| Element | Use | Gain | Cost | Verdict |
| --- | --- | --- | --- | --- |
| Titel field as the page heading | one fact, one place | high | — | keep |
| Input frames in the secondary ink | show where to type | high | 20+ dark frames = the "too many lines" the owner criticised in August | **fixed**: new `--edge` token (≥3:1, lighter than ink-2). A line has two jobs: a connector may be faint (`--rule`), an affordance edge must meet 3:1 (`--edge`) |
| Seven section headings at page-section size | orientation in a long form | mid | most of the page's visual weight after the title | **fixed**: subhead role — still clearly above the labels (the August critique) |
| "Datierung (EDTF)" label + "(EDTF)" in the hint | — | none for volunteers | jargon twice | **cut** both; the examples teach the syntax |
| Media rows: ↑ ↓ × | reorder, remove | high | "×" is ambiguous and a second word for "Entfernen" used in Weitere Angaben | **fixed**: "Entfernen" as the same quiet text control |
| "Als Entwurf zurückziehen" as a framed button under Speichern | — | rare | a consequential rare action at the same weight as the frequent one | **moved into "Mehr …"** — frequency decides visibility |
| Conflict: list of differing fields with lines between | jump to each field | high | lines between one-ended rows separate instead of connect | **fixed in the system**: register rows get a line only when they have two ends |
| Conflict: "Inzwischen gespeichert: …" under each field | the other person's value where the decision is made | high | — | keep |
| New article: "Kerndaten" heading over one field | — | none | a heading for a single select | **cut** |

## System changes made during the review (`system/system.css`)

- `--type-subhead` (serif 1.35rem) and the `--section-head-type` knob.
- `--h1-type` knob on `h1`; `split` sides set it to the heading role.
- `.facts :is(time, data)` inherits the fact font — no mono for single values.
- `--measure-prose` token.
- `--edge` / `--page-edge` token for control edges (≥3:1), separate from `--rule`.
- `register`: a row gets a line only if it has a figure or a lead (two ends).

## Open questions for the owner (from the writers' NOTES, deduplicated, plain terms)

1. **Check page:** new value stated once, rows show only the old value. Right, or keep "{alt} → {neu}" on every row as the named pattern literally says?
2. **Draft article:** "Veröffentlichen" and "Bearbeiten" both open the form. Publish directly from the article page (the audience is already shown), or merge the two?
3. **Published article:** show its audience to archivists as a quiet line too ("Sichtbar für: Alle Mitglieder")?
4. **"Bestand bearbeiten"** starts from the "+ Neu …" create menu today. A quiet link in the search sentence when one Bestand is set?
5. **Bestand description** (ruled optional 2026-08-22) is not in the forms yet — add now?
6. **Rare article actions** (Kopieren, Zurückziehen, Löschen) behind "Weitere Aktionen …" — fine for weekly archivists?
7. **Delete wording:** mention that the admin's Nextcloud bin may still hold the files, or keep "no bin, cannot be undone"?
8. **Selection boxes:** hover-reveal until the first tick, always on touch — or always visible?
9. **Preview pane ("Vorschau")** in the list: drop it (the title opens the article, Back returns), or keep for archivists checking many records?
10. **Bulk edit on phones:** absent — acceptable?
11. **Commit wording:** always "überschreiben", or "setzen" when records had no value?
12. **Deleted records in the bulk result:** title if known, or only a count?
13. **"Sammlungsteil" vs "Bestand"** in the field chooser — rename to "Bestand"?
14. **Edit form on phones:** Speichern scrolls away; add a sticky save bar (costs ~1/7 of the screen)?
15. **Conflict:** a per-field "übernehmen" action? And should Speichern say "Trotzdem speichern" after a conflict?
16. **Datierung echo:** show it only when it differs from the input ("1962" → "1962" says nothing)?
17. **New article:** keep the two-step flow (Titel + Bestand, then the full form) or the full form at once?
18. **L size:** page content never exceeds ~74rem, so container-L never triggers; the form writer keyed its layout to the viewport instead. Lower the L threshold, grow the measure, or judge L on the viewport?
