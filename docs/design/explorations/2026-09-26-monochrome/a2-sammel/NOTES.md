# a2-sammel — the archivist's list and bulk edit (one field across selected rows)

Pages: `liste.html` (archivist list, nothing selected; hover a row) · `liste-auswahl.html`
(3 rows selected, bulk bar active) · `pruefen.html` (check) · `pruefen-fehler.html` (error
mode) · `ergebnis.html` (result with conflicts). CSS: `a2-sammel.css` (additions only).

Mock story: the archivist moves the Gau Wartburg magazines on page 1 into one new box. They tick
"Die Feuerrunde Heft 2" (BA 1588), "Die Feuerrunde, Heft 1/79" (BA 523) and "Wartburg-Bote,
Nr. 36" (BA 1611) and set Standort to "Gruppen des DPB -- Gau Wartburg -- Zeitschrift -- Box 1".
The old Standorte are real (`data.json`); the new value is the archivist's input. Mock-only
data: the Entwurf mark on "Führerbrief des Gaues Wartburg 53" (a visible note on the list says
so) and the result outcome (1 saved, 2 changed by someone else).

## Screen jobs

### Liste (archivist view)

Who: archivists, weekly, on L with a pointer. Job: find records, open one to check or correct
it, and now and then pick several and change one field on all of them. Success: the list reads
exactly like the member list until the archivist reaches for a row; picking and editing never
cost a member-style scan anything.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Search sentence head (as r4) | low | high | keep, unchanged |
| Selection box per row, always shown | mid (25 boxes, a second column of marks) | high only while selecting | **not** always shown on pointer devices |
| Selection box, shown on row hover/focus | low | high | keep. It hangs in the page gutter, so titles stay aligned with the head and nothing jumps when it appears |
| All boxes shown once one is ticked | low | high (the archivist is now selecting on purpose; ticked rows must stay findable) | keep |
| Row marking for a ticked row (real: inverted row) | high (black bands) | none (the archivist just ticked it; the filled box says it) | cut: "Don't signal what the user already knows" |
| "Bearbeiten" at the row end, on hover/focus | low | mid-high (skips the article page when the archivist already knows what to fix) | keep, hover/focus only |
| "Bearbeiten" always shown | high (25 repeated words) | same | cut |
| "Vorschau" + preview pane (real `_pane.html`) | high (a side column squeezes the list; a third way to see one record) | mid (checking many records in a row without leaving the list) | **not mocked**; open question 2 |
| Entwurf mark after the title | low | high | keep (system `mark`) |
| Pager | low | high | keep |
| Touch devices (no hover) | — | — | boxes and "Bearbeiten" always shown, as today |

Judgment on today's hover-reveal: it is right for "Bearbeiten" and right for the boxes *at rest*,
but not once selecting has begun. The rule "Hide a control only if it can never become active
here" says hover-reveal is wrong in principle (the box is always active). Its boundary saves it:
the box appears under the pointer the archivist is already moving to that row, on purpose, in a
column that is always reserved, so nothing jumps. After the first tick every box shows, because
from then on hiding them would hide the state of the selection.

### Liste mit Auswahl (bulk bar)

Job: say which field gets which value on the ticked rows, then go check it. Success: one line,
readable as a sentence, reachable without scrolling back up.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Bar under the ledger, sticky to the viewport bottom | mid (covers the last visible rows) | high (the selection's controls stay in reach at any scroll depth; appearing does not push the rows down) | keep. Real: a `<details>` above the ledger, which pushes all rows down when it appears |
| Collapsed "Sammelbearbeitung …" summary | mid (one more click after a deliberate tick) | low (ticking only serves this) | cut; the bar opens with the first tick |
| "3 ausgewählt" | low | high (the pager's rule: state lives with its controls) | keep, first in the bar |
| "Alle auf dieser Seite" · "Auswahl aufheben" | low | mid | keep (real) |
| Feld · Neuer Wert as one sentence: "[Standort] auf [neuer Wert] setzen" | low | high (same voice as the search sentence) | keep; the real labels become the select's first option and the field's aria-label |
| "Änderung prüfen" (primary) | low | high | keep; the only solid button on the page while selecting |
| Bar on S | high (half a phone screen) | low (bulk work is L) | absent, and so are the boxes |

### Prüfen (Consequence disclosure)

Job: see exactly what will be overwritten, record by record, before committing. Success: the
archivist can point at each old value that will be lost, and the button says what happens.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Heading "Änderung prüfen" + one sentence ("Der Standort wird bei diesen 3 Artikeln ersetzt.") | low | high | keep |
| Summary panel Feld · Neuer Wert · Betroffen: n (real) | mid | low (the sentence, the rows and the button say all three) | cut |
| Separate "Betroffene Artikel" list (real) | mid | none once each row shows its change | merged into the one table |
| One row per record: Titel + quiet Signatur · bisher · → neu | mid | highest (the disclosure itself) | keep. Old value one tier quieter, new value bold, no color. Signatur quiet mono after the title (Signatur ruling, point 3) |
| The new value repeated in every row | mid (bold ×n) | mid (each row is a complete statement; with a Medienart change the second consequence differs per row) | keep; the pattern asks for it |
| Button "3 Standorte überschreiben" | low | high (names field, count and that data is replaced) | keep; replaces "Auf 3 Artikel anwenden", which only counts |
| "Abbrechen" back to the selection | low | high | keep (real) |
| Header link "Zurück zur Suche" (real) | low | low (Abbrechen does it, keeping the selection) | cut |

### Prüfen, Fehler

Job: fix the one wrong input without losing the selection. Success: the message sits right above
what it is about; the typed value is still there.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| "3 ausgewählt" | low | mid (the selection survived) | keep (real) |
| Error text, red, before the sentence | low | high | keep, verbatim ("Bitte ein Feld wählen."); the select's underline turns red too |
| The same chooser sentence, value re-echoed | low | high | keep (same component as the bar) |
| "Zurück zur Auswahl" | low | mid | keep (real) |
| List of the selected records | mid | low (nothing is overwritten on this page) | not added |

### Ergebnis (Conflict is not an error)

Job: know what got saved, and deal with what did not. Success: the archivist sees the count,
opens each unsaved record in one click, or re-selects them all at once. Nothing looks alarming.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Heading "Sammelbearbeitung teilweise abgeschlossen" | mid (long, wraps at L) | high | keep; wording open (question 5) |
| "Standort → neuer Wert" | low | mid | keep, one quiet line |
| "1 gespeichert · 2 inzwischen geändert" | low | high (successes are counted, not listed; signals once) | keep |
| "Die Suche zeigt einige Änderungen in Kürze." | low | mid (explains a list that still shows the old value) | keep, only while the index lags |
| Section "Nicht gespeichert" + one sentence that says the records are unchanged | mid | high (the only thing to act on) | keep; says why and that nothing was half-written |
| Per-row mark "inzwischen geändert" (real) | low | none (the section says it for every row) | cut: "No redundant marks" |
| Per-row "Diesen Artikel bearbeiten" | low | high | keep |
| "Diese 2 erneut auswählen" | low | high | keep, as the one outlined button |
| "Zurück zur Suche" | low | mid (browser Back would land on the POST) | keep as a plain link |
| "Nicht mehr vorhanden:" bucket (real, lists raw ULIDs) | — | — | not in this mock outcome; it would take the same quiet rows, without a link. A ULID means nothing to an archivist (question 6) |

## Rules whose boundary I hit

- **Hide a control only if it can never become active here** — hover-reveal of the selection box
  and "Bearbeiten". Kept under the boundary (opened on purpose, reserved slot, no jump); lifted
  for the boxes once selecting has begun. The bulk bar also appears on the first tick; same
  boundary (the tick is deliberate). No-JS baseline: the bar stays visible, as today.
- **A line connects or anchors** — the bulk bar's top line is not a row connector; it is the edge
  between the bar and the rows scrolling behind it. At rest it sits right under the last row.
- **Mono only for data in columns** — "3 ausgewählt" and the counts on the result page are sans,
  running text. The Signatur after the title on check/result pages stays mono (Signatur ruling).
- **Space budget** — bulk editing is absent on S (boxes, "Bearbeiten", bar). Check and result
  pages work on S, stacked.

## Proposed system additions

All in `a2-sammel.css`, written to the system's rules (one root class, knobs line, tokens only).

| Addition | Job | Why no existing component fits |
| --- | --- | --- |
| `ledger-pick`, `ledger-act` (two ledger cells) | the selection box hanging in the gutter, the row-end action slot; hover/focus reveal, all boxes once one is ticked; S absent | they are ledger columns; their S rendering and the row hover belong to the ledger, so they are cells of it, not a new component. Proposed as part of `ledger` |
| `bulkbar` | the selection's sticky bar: status + the chooser | nothing in the system sticks or holds a selection state |
| `chooser` | "[Feld] auf [Wert] setzen [Änderung prüfen]" as one sentence; error line; a styled `select` | `search-sentence` is a heading with filter buttons; it has no select, no submit, no error line. The system styles no `select` at all |
| `affected` | one quiet row per touched record: Titel + Signatur · bisher · → neu · one onward link | `ledger` has fixed columns (Datierung, Typ); `register` has one label and one figure. The diff grammar ("alt → neu", weight not color) exists nowhere yet. Serves both check and result pages |
| `cluster` (layout) | a wrapping row of buttons/links | the system has no row layout; pages would otherwise need inline flex styles |

## Open questions for the owner

1. **Selection boxes: hover, or always?** On a mouse, the mocks show each box only when the row is
   hovered, and all boxes once one is ticked. On touch they are always shown. Is that the right
   balance, or should archivists see the box column all the time?
2. **The preview pane ("Vorschau").** Today each row can open a side preview of the record. The
   new navigation has no side pane, and the title opens the article in one click (Back returns to
   the list). Drop the preview, or keep it for archivists who check many records in a row?
3. **Bulk edit on the phone.** The mocks drop selecting and bulk editing on small screens. Is that
   acceptable, or do archivists ever need it on a phone?
4. **The commit button's words.** "3 Standorte überschreiben" says what is lost. When some
   records have no value yet, "setzen" would be more exact. One word for all cases
   ("überschreiben"), or switch by case?
5. **Result heading.** "Sammelbearbeitung teilweise abgeschlossen" (today's words) wraps to two
   lines and says little. Something like "1 von 3 gespeichert" instead?
6. **Deleted records in the result.** Today they are listed by their internal ID, which means
   nothing to an archivist. Show the title (if still known), or only a count ("1 Artikel gibt es
   nicht mehr")?
7. **"Sammlungsteil" vs "Bestand".** The field list says "Sammlungsteil"; everywhere else (and in
   its own error message) it is "Bestand". Rename the field option to "Bestand"?
8. **Long values in the bar.** On a large screen the value field is about 40 characters wide
   before it scrolls; Standorte are often longer. The check page shows the full value. Enough,
   or should the bar give the field its own line?
