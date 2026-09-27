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
16. ~~**Datierung echo:** show it only when it differs from the input?~~ Answered 2026-09-27: echo cut (see rulings below).
17. **New article:** keep the two-step flow (Titel + Bestand, then the full form) or the full form at once?
18. **L size:** page content never exceeds ~74rem, so container-L never triggers; the form writer keyed its layout to the viewport instead. Lower the L threshold, grow the measure, or judge L on the viewport?

## Owner rulings on a1 (2026-09-27, applied)

- **Title field:** the "Titel" label above the heading is noise, and so is the frame. Both are
  gone. It is now a shared component `title-field` in `system/system.css` (with a gallery entry),
  used by all three a1 pages. The textarea names itself (`aria-label`); the placeholder "Titel"
  shows while it is empty. An edge shows under it on hover, and focus thickens that edge to the
  focus width. The underline is the focus signal, as in `search-field`.
- **Datierung:** one help line at most. The "z. B." line stays; the read-back ("um 1960") is cut.
  A circled "?" at the end of the line opens a native popover with the full notation list.
  Click, tap and keyboard open it; hover never does. New component `help` in `a1-formular.css`
  (proposed, not yet in the system).
- **Standort is not Herkunft.** It is where the physical original is kept (legacy label
  "Standort (analoges Archiv)"). It moved to Kerndaten after Signatur and takes the full row,
  because its shelf paths are long. Herkunft keeps Autor and Ort.
- **Open, raised by the owner:** mark private/public and required/optional fields; which
  legacy terms to adopt (the legacy form said "Sammlungsteil", not "Bestand"; see question 13).


## Owner rulings on a1, round 2 (2026-09-27, applied)

- **Title field scrollbar:** the box sized to the 1.08 line height while the serif glyphs reach
  past it, so the difference scrolled. Fixed in `title-field`: a hair of padding, and no overflow
  where `field-sizing: content` grows the box.
- **Crumbs** did not read as navigation and "Bund" alone did not say what it is. System change:
  the steps are underlined links, and the trail starts with "Archiv" (the one list), so it reads
  as a place: "Archiv › Bund". Applied to every page that has crumbs.
- **Help "?":** a CSS circle one line high (`1lh`), not an icon font.
- **Select:** native inset dropped (`appearance: none`); text starts where an input's does, and a
  hairline chevron sits at the same inset from the edge.
- **Medien row tools:** the app's stroke icons; disabled arrows in the faint line colour; the
  remove is a cross.
- **Rule: a destructive control turns red on hover, press and focus** (unless it is red already).
  Destructive = deletes for good. It applies to the media cross, "Löschen" in "Mehr …" and the
  confirm button. A cross that only drops a value from the unsaved form (a chip, a Weitere
  Angaben row) stays neutral and asks nothing.
- **Confirm before deleting a medium:** the cross opens a popover with the consequence
  ("… das lässt sich nicht rückgängig machen") and a red "Entfernen". Light dismiss or "Abbrechen"
  cancels. The app already asks in two steps; the popover keeps it next to the cross.
- **Upload:** one "Dateien hinzufügen" button; the hint "Neue Dateien kommen ans Ende …" is cut
  (the new row and the Titelbild mark say it).
- **Chips** (new component) for Schlagworte and Gruppen: chosen values inside one field edge, then
  an input that suggests from a datalist. The Feld of Weitere Angaben takes one value, so it gets
  the datalist without chips.
- **Weitere Angaben:** no empty pair; each filled row has a cross; "+ Angabe hinzufügen" adds a row.
- **Open:** does Zugriff move into the form's margin? (Owner: needs deeper thought.)

## Owner rulings on a1, round 3 (2026-09-27, applied)

- **Help:** the literal character ⓘ (U+24D8), no icon.
- **Textareas:** `min-block-size` in `lh` (a `--field-lines` knob; Beschreibung 6) and
  `field-sizing: content` as progressive enhancement.
- **Zugriff moved into the margin** (owner accepted the recommendation): the consequence line is now
  the control, "Sichtbar für [Alle Mitglieder (wie Bestand) ▾]". The inherited option names its
  value. Gruppen shows only for "Bestimmte Gruppen" (CSS `:has`, no JS; visible where `:has` is
  missing). The Zugriff section is gone.
- **Select:** native chevron kept. Its spacing cannot be set cleanly (`appearance: base-select`
  would restyle the whole picker, Chrome only); revisit later.
- **Datierung belongs to Herkunft** (who, where, when). Moved.
- **Autocomplete** is now a working system component (`system/autocomplete.js` + CSS, gallery entry):
  single mode for Medienart, Dokumenttyp and the Feld of Weitere Angaben (free text allowed);
  multiple mode (chips) for Schlagworte and Gruppen. Phrases like "Motiv: Tony Wirtz" are one value.
  Without JS the plain input and the native datalist remain; the server contract (comma list) does
  not change.
- **Medienart and Dokumenttyp** become free text with suggestions (CONTEXT.md already says so; the
  app still validates against a fixed list — an app change for later).
- **Label cursor:** `.button` sets `cursor: pointer`, so a `label.button` (file chooser) matches.
  Not `role="button"`: the label must stay a label for its input.
- **Field markers:** "*" after required labels (Bestand, Medienart; Titel is the heading) with
  `required` on the control; "intern" at the end of the label line (Standort) and in the section
  head (Weitere Angaben). The "Nur intern sichtbar" hint is gone.
- **Sammlungsteil vs Bestand:** keep "Bestand"; wait for archivist feedback.
- **Legacy fields:** Querverweis is empty in all 2506 rows (dropped at import); it is offered as a
  suggestion for the Feld of Weitere Angaben, with the other legacy keys.

## Owner rulings on a1, round 4 (2026-09-27, applied)

- **Inheritance rule** (new principle in `RULES-DRAFT.md`): a part sets only what differs from its
  context. The "*" marker lost its class and colour; `.help` keeps only its margin. The elements
  layer now resets form controls once (`font`, `color`, `letter-spacing: inherit`, one
  `::placeholder`), and restated colours were deleted across the mock CSS.
- **Conflict view:** the conflicting fields carry `aria-invalid="true"` and show the error edge (the
  chips box too). Not the `:invalid` pseudo-class: that needs `setCustomValidity`, which would block
  the save that resolves the conflict. The notice "Inzwischen geändert" now leads the margin: a heavy
  red rule, a red subhead, `role="alert"`.
- **Media delete asks with `hx-confirm`** (the browser's own dialog; without JS the app's server
  two-step stays). The confirm popovers are gone.
- **Menu = a real popover component** in the system (`button.menu-button` + `ul.menu[popover]`),
  replacing `<details class="menu">` on every page (top bar "+ Neu …" included).
- **Menu entries:** "Ansehen" → "Zur Artikelseite"; "Kopieren" → "Duplizieren"; "Als Entwurf
  zurückziehen" is gone — the publication state is one control in the margin: "Status
  [Veröffentlicht | Entwurf (nur Archivare)]", applied by Speichern. One place for the state.
- **Versions:** a quiet margin line "Version 4, gespeichert am … von … · Alle Versionen" marks
  where history will open. The versions screens are not designed yet (open question).
- **Tags import:** the legacy archive separated Schlagworte by line. The import splits on line
  breaks and `--` (used as a separator inside lines in 860 rows), no longer on spaces. The old
  docstring's claim that the word split was the owner's call was false and is corrected.
- **Open:** `role="button"` on the upload label (see the reply of 2026-09-27: it would nest the
  file input inside a button role that keyboard focus never reaches).

## Owner rulings on a1, round 5 (2026-09-27, applied)

- **One cross:** `.remove` is the only removal control (media, Weitere Angaben, chips): red on hover,
  press and focus everywhere. Where it deletes for good it also carries `hx-confirm`. The
  Weitere Angaben cross is centred on its input.
- **Conflict notice:** the changed fields are links inside the sentence ("Prüfe Schlagworte,
  Datierung und Beschreibung und speichere erneut"); the block's gaps tightened.
- **"intern" is a quiet note touching its host** (new system component `note`: `--type-note`,
  `--ink-3`), right after the label or heading, not at the far edge.
- **Upload:** "+ Dateien hinzufügen" in the `add` voice, no frame.
- **Error edge doubled** (border + inset) in light and dark: a 1px red line did not stand out.
- **Dark mode:** new token `--faint` for present-but-inactive things (disabled arrows, placeholder
  drawings), tuned up in dark where `--rule` vanished; one shared `--placeholder` drawing replaces
  three copies.
- Owner: "In general, I like the new monochrome look."

## Owner rulings on a2 / a3, round 1 (2026-09-27, applied)

- **Scope:** the delete, new-Bestand and edit-Bestand screens are low priority; not reviewed further
  before the page waves.
- **"Artikel ohne Medien" was wrong twice:** it had media (a video), and it had no hierarchy (text and
  facts side by side, equal weight). Renamed `artikel-video.html`. The video leads on the plate like
  every article's media, as the native player (knob `--plate-lead-ratio: 16 / 9`); its name, kind,
  size and "Herunterladen" sit right under it (`plate-file`), not at the far edge of a row. A file
  with no player (e.g. a document without a preview) is still open.
- **Section heads:** the aside ("Gruppen des DPB · alle ›", "nach Jahrzehnt", "später") touches its
  heading instead of floating at the far edge. System change; checked on start, article, video.
- **Bulk edit:** no bottom bar. While a row is picked, the ledger's column heads give way to the
  archivist toolbar in the same row (CSS `:has`, no JS, no row moves): the page box, "3 ausgewählt",
  "Auswahl aufheben", then "Feld ändern …" right after them. "Feld ändern …" opens the chooser
  sentence in place (`details`). The row sticks to the top while the list scrolls. New state page
  `liste-feld.html` (step two). Cost: the sort heads are gone while rows are picked.

## Owner rulings, round 2 on a1 / a2 / a3 + start (2026-09-27, applied)

- **a1 media row:** the file name and its caption belong together. They now stack in one column next
  to a larger preview (`--measure-thumb`, 8rem); name and size share one line; the tools sit level
  with the caption input, right after it (the body column stops at the query measure).
- **a3 article:** crumbs and title sit at the page's start edge, above plate and text (inline-start,
  block-start). Facts are one line each ("Datierung 1967"), the label column as wide as the longest
  label: six facts take six lines, not a quarter screen.
- **Onward lists (lead + label):** the lead column is as wide as the longest lead in that list, capped
  at one full date; an EDTF range breaks after its slash (`<wbr>`), tested with
  `1984-11-26/1995-03-14`. Lead and label touch, so these rows have no rules. System rule: a register
  line connects a label to a far figure; a lead row gets none.
- **a2 list:** the last column shrinks to its content, so the row rules end where the content ends;
  "Bearbeiten" follows the title in its cell (hover) instead of a row-end column.
- **a2 toolbar:** no sentence form. One tool row over the column heads, always in place: at rest only
  "Spalten …" (the column chooser, a check list), at the end edge; once rows are picked the start
  shows "3 ausgewählt · Auswahl aufheben" and the tools "Feld ändern …", "Verschieben …", "Mehr …"
  (Veröffentlichen, Als Entwurf zurückziehen, Löschen …). Each tool opens its own anchored popover
  panel (`toolpanel`) or a menu; a new tool is one button or one menu entry. The column heads (and
  sorting) stay while rows are picked. Only "Feld ändern …" exists in the app today.
- **Start page:** the Zeitleiste stretches between its neighbours' first and last rows (its rows lose
  their own padding; the stretch spaces them). "Nach Art" shows as many rows as "Bestände" (top eight
  plus "Weitere Arten"), so all three columns end level.

## Owner rulings, round 3 on a3 (2026-09-27, applied)

- **Facts distilled:** the labelled fact list is gone from the article. The origin is one line under
  the title with no labels, because its values are self-evident: "CD / DVD · 2007 · Iserlohn · von
  Ring Florian Geyer" (new system component `byline`).
- **Signatur and Standort are management info,** not facts about the article: a quiet, labelled
  `byline` right after the archivist's actions ("Signatur BA 1035 · Standort …"), meta size.
- **One typeface for the running text:** origin and Beschreibung share the body type.
- **Semantic HTML:** every date is `<time datetime>`; an EDTF qualifier stays in the text
  (`<time datetime="1963">1963~</time>`), a range is two `<time>` elements. Counts and Signaturen
  stay `<data>`.
- **Onward lists grouped by space:** without lines, a row's own lines sit one leading apart and rows
  sit a clear gap apart (`--space-5`), so a wrapped title stays with its date instead of drifting
  toward the next row.

## Owner rulings, round 4 on a3 (2026-09-27, applied)

- **The title area was cluttered and the hierarchy off:** five voices under one another (crumbs, serif
  title, origin, a bold framed button row, a labelled meta line), and the archivist's tools stood
  between the title and the content. The title area is now crumbs, title and origin only: three
  voices. Content (media, Beschreibung) comes next.
- **The archivist block** closes the text column, after the content it manages, in one quiet meta
  voice: the draft's audience line, "Signatur … · Standort …", then "Bearbeiten · Weitere Aktionen …"
  (text, no framed button; editing is not the page's primary task — reading is).

## Owner rulings, round 5 on a3 (2026-09-27, applied)

- **The archivist block at the end of the text column had no structure and was hard to find.** The
  tools now share the record's first line with the crumbs, at the end edge (`record-head`):
  "Bearbeiten" as a button, then one "more" icon button (new sprite glyph `more`, accessible name
  "Weitere Aktionen") for the rare actions — all of them archivists' only (Duplizieren, Als Entwurf
  zurückziehen, Löschen). A draft adds "Veröffentlichen" (primary) first.
- **The Signatur leads the origin line, without a label:** "BA 1784 · Foto(s) · 1967 · … · von mo".
  Standort (archivists) closes the line, quiet, with its label; a draft adds "nach Veröffentlichung
  sichtbar für …" there too.
- **The Beschreibung anchors to its title:** it follows the origin line as the record's lede, at
  reading measure. The media come after it at full width: the lead image takes half, the further
  sheets fill a two-by-two grid beside it (`plate` knobs `--plate-lead-span`, `--plate-lead-rows`);
  a video lead spans the full width.
- **Byline wrapping:** no line starts with a dot (the separator slot of a line's first item is
  clipped).
- **Round 5b:** the "more" glyph is vertical (⋮) and stands before the buttons; a framed button is
  last, so its corner shapes the page's corner at the end edge (a draft closes with Veröffentlichen).
