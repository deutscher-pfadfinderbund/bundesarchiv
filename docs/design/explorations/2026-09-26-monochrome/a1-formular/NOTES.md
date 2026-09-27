# a1-formular — the article form (edit, conflict, create)

Pages: `bearbeiten.html` (edit), `bearbeiten-konflikt.html` (the "Inzwischen geändert" state),
`neu.html` (create). All three are built from `../system/system.css` plus `a1-formular.css`.

Sample: BA 860 "Die Kompassnadel, Nr. 20" (data.json: Bund, Schrifttum/Zeitschrift, 1960~,
Deutscher Pfadfinderbund, Bonn). I picked it because its Datierung has an echo that says more
than the input ("um 1960"). Made up for the mock: the three media files, their sizes and the one
caption; the Legacy-ID value 1293; the whole conflict scenario (someone else stored Datierung
1960-03 while this archivist typed Schlagworte and a Beschreibung). Schlagworte and
Beschreibung are empty on `bearbeiten.html`, as they are in the imported record.

## The composition (field-agnostic, ADR 0009)

Three parts, none of which knows a field by name:

- **Lead field**: the registry's heading field (Titel), drawn at title size inside the page's h1.
  Nothing else repeats it. Above it are the crumbs, which show the place (the Bestand).
- **Sections**: a `section-head` (serif h2) over a `field-grid`: aligned cells, at most two per
  row, `data-span="all"` for prose. Every field is the same `field`: label, boxed control, and
  under it its echo, conflict line, hint or error. Sections come in E1 order and are all open.
- **Meta margin** (`record-meta`): the record's state, one line of consequence, then the actions.
  On L it is a sticky side column. Below L it sits under the Titel, before the first section.

The registry's `fit` width classes (`kurz`, `signatur`) are no longer needed here. The cell is
the unit of width, and every control fills its cell. The only width fact a field still needs is
"takes the whole row" (Beschreibung).

## Job tables

### Bearbeiten (edit an article)

Who: archivists, weekly, on L. They want to correct one record fast (most often a field in
Kerndaten or Einordnung), sometimes to finish a draft and publish it, and sometimes to add
scans. Success: they find the field, change it, save, and know what the save did and who now
sees the article.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Crumbs (Bestand) | low | mid: where the article lives, one click to that list | keep, quiet |
| Titel as the page heading (framed, title size) | low (it would be the heading anyway) | high: identity and the most edited field in one place | keep; no second h1 |
| "Titel" label above it | low | mid: says this heading can be edited | keep, quiet |
| Section heads (serif h2) | mid | high: rank and a way to find things in a long form | keep |
| Boxed inputs, all one height | mid (13+ frames) | high: the frame is the edge you click; a filled field and an empty one look alike | keep; frame at ink-2 (see questions) |
| Hint / echo under its field | low | mid–high: the Datierung echo checks the EDTF | keep, next to the field |
| Two fields per row on L and M | low | high: the form is half as long | keep |
| Medien register (thumb, name, caption, ↑↓×) | mid | high: order is meaning (the first is the Titelbild) | keep, inside the column |
| "Titelbild" mark on the first row | low | mid: says why order matters | keep |
| Native file input + "Hochladen" | low | high | keep; the pair is labelled "Dateien hinzufügen", with a hint about order |
| Meta margin: state word | low | high: Entwurf or Veröffentlicht decides what the next button does | keep |
| Meta margin: one line of consequence ("Sichtbar für alle Mitglieder.") | low | high: who sees it, always on screen (G.34) | keep |
| Old exposure card, "Sichtbare Felder: …" list | high | low: the hidden field says so itself ("Nur intern sichtbar") | cut |
| Signatur chip in the margin | mid | none (owner ruling) | cut |
| Speichern (primary) | low | highest | margin, first submit button, sticky on L |
| Lifecycle action (Veröffentlichen / Als Entwurf zurückziehen) | low | high | margin, next to the line that states its consequence |
| "Mehr …" (Ansehen, Kopieren, Löschen, Verwerfen for drafts) | low | mid, rare | margin, folded |
| "Zurück zur Suche" | mid (it confused next to the badge) | low: browser Back keeps the search | cut (navigation rule) |
| "Nicht gespeicherte Änderungen" | low | mid | same state slot, JS only (not shown in the mock) |
| Header search | mid | low here: it invites leaving a form with unsaved edits | absent on the forms (see boundaries) |
| Folds with summaries (Herkunft, Zugriff, Weitere Angaben) | mid (open/closed mix) | low | cut; all open (owner ruling) |

### Bearbeiten, conflict ("Inzwischen geändert")

Who: the same archivist, right after pressing Speichern, when someone else saved first. They
want to know what differs, decide field by field, and save again. Success: they see every
differing field without reading a table. Nothing looks like their own mistake.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| State "Inzwischen geändert" in the margin's state slot | low | high | keep; no red, no alert tone |
| The real sentence ("Ein anderer Bearbeiter … Bitte prüfen und erneut speichern.") | low | high | keep, as the consequence line |
| List of differing fields, each a link to its field | low | high: an overview, and the onward action per row | keep (the `register` component) |
| "Inzwischen gespeichert: …" under each differing field | low | high: the decision is made at the field | keep; it replaces the three-column diff table |
| The three-column diff table (Feld · Deine Eingabe · Inzwischen gespeichert) | high: a second copy of every value, far from its field | mid | cut; the field shows your input, the line under it shows the stored value |
| Lifecycle line ("Veröffentlicht, sichtbar für alle Mitglieder.") | low | mid: a second line, but the lifecycle button still needs its consequence | keep |

### Neu (create an article)

Who: archivists starting a record, often with the object in hand. They want a record to exist
fast, then catalogue it. Success: type a title, pick a Bestand, press Enter, and land in the full
form with the caret on the first empty field.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Titel as the lead field, autofocused | low | high | keep, same as edit |
| Kerndaten with Bestand | low | high: the other required field | keep |
| Meta margin: "Neuer Artikel" + "Wird als Entwurf angelegt; die übrigen Angaben folgen danach." | low | mid: names the page (the heading is still empty) and says what Anlegen does | keep |
| Anlegen (primary) | low | highest | margin, the only action |
| Crumbs | — | none: no place until a Bestand is chosen | absent |
| "Neuer Artikel" h1 | mid | low: the margin names the page; the Titel is the heading | cut |
| The other sections | high | low before the record exists | absent (real flow: create, then edit) |
| "Bestand „…“ angelegt." status line | low | mid, only after the create-a-Bestand detour | state slot of the margin (not shown) |

## Proposed system additions (`a1-formular.css`)

| Addition | Kind | Job | Why no existing part fits |
| --- | --- | --- | --- |
| `field` (knobs `--field-type`, `--field-edge`; parts `-label`, `-hint`, `-error`, `-was`; the select draws its own chevron) | component | one form field: label over a boxed control, its messages under it | the system has no form control. The base `input` is an underline, which the owner rejected for forms. `facts` is read-only |
| `record-meta` (parts `-state`, `-line`, `-actions`) | component | the form's margin: state, consequence, actions | `section-head-aside` holds one link, not a state plus actions. `resume` is a sentence of links |
| `file-row` (parts `-thumb`, `-name`, `-tools`) | component | one medium in the Medien register | `register-row` is label plus figure. `media-item` is a gallery tile whose first child spans two cells. Lines come from `register`, so `file-row` only lays out the row |
| `upload` | component | "+ Dateien hinzufügen" (an `add` label) over a hidden file input; files upload on choose | a file input's native button text cannot be set. Upload on choose needs JS; without JS the app shows the native input and a submit, as today |
| `help` | component | a circled "?", one line high, that opens a `popover` with details a hint has no room for | a hint is one line by rule; `abbr` titles never open on touch or keyboard |
| `popover` | component | the surface a `help` opens (native `[popover]`, anchored on M/L) | `menu` holds actions, not an explanation |
| `remove` | component | the one cross for every removal; red on hover, press, focus; hx-confirm where it deletes for good | words ("Entfernen") read as a link |
| `add` | component | "+ …" adds one more row of its kind | the top bar's "+ Neu …" is a menu, not a form action |
| `pairs` | layout | one custom-bag row: Feld · Wert · remove | `field-grid` has no slot for a trailing control |
| `form-sheet` | layout | lead · margin · body; margin sticky on L | `split` is media / facts by flex-basis and has no named areas or sticky side |
| `field-grid` (knob `--field-grid-min`) | layout | aligned cells, at most two per row | `columns` uses section gaps and has no two-column cap |

Token check (grep for hex, raw rem/px, font shorthand outside `var()`): clean. The two literal
`40rem`/`80rem` stand only in `@container` / `@media` conditions, as in the system.

## Rules whose boundary I hit

- **Container sizes vs page layout.** `.page` is the size container, but its content box is at
  most 74rem (80rem measure minus gutters). An `@container (width >= 80rem)` never fires.
  `form-sheet` therefore asks the viewport (`@media (width >= 80rem)`). Components inside still
  query their container: the form body is its own container.
- **Frames only as an input's edge.** Used exactly so. The margin, the Medien register and the
  sections have no frames. Alignment and space group them.
- **Mono only for data in columns.** Signatur and Datierung inputs are sans: an input is not a
  column.
- **Top bar.** Copied from `r4-system/archiv.html` (no compact search). The forms are not
  article pages, and a search box on a form invites leaving with unsaved edits. "Open: compact
  header search on article pages" is still open for the article page itself.
- **Consequence disclosure.** A conflict save overwrites the other person's values, which is the
  case where the pattern says the button names the consequence. I kept "Speichern" (see
  question 3).

## Known issues (after the one fix batch)

- ~~Disabled ↑/↓ hard to tell apart~~ Fixed 2026-09-27: enabled tools ink-2, disabled in the line colour.
- Autocomplete sources: Schlagworte and Feld can suggest what the archive already uses. Gruppen
  has no source in the app today (groups come from Keycloak tokens only): it needs one, for
  example the groups already named on articles and Bestände plus the archivist's own groups.
- The screenshots show the file chooser in English ("Choose Files"). The headless browser
  ignores the page locale here. A German browser shows "Dateien auswählen".

## Open questions for the owner

1. **Input frame strength.** The input frames use the secondary ink (dark gray), not the light
   hairline gray. A hairline-gray frame would be quieter, but at about 1.4:1 contrast people
   with weaker eyes would not see where the field is. Is the dark-gray frame quiet enough, or
   should the frame be quieter and the label carry more?
2. **Conflict: a per-field "übernehmen".** Each differing field shows "Inzwischen gespeichert: …"
   under it. Should that line get a small "übernehmen" action that puts the stored value into
   the field? Today the archivist has to retype it. It would be a new action.
3. **Conflict: the save button's words.** After a conflict, Speichern overwrites what the other
   person saved. Should the button then say so (for example "Trotzdem speichern"), as the
   consequence-disclosure pattern asks, or is the sentence in the margin enough?
4. **Speichern on phones.** On L, Speichern sits in a margin that stays on screen while you
   scroll. Below L it sits under the Titel and scrolls away, so after editing Medien the
   archivist scrolls back up. Is that fine (archivists edit on large screens), or should small
   screens get a save bar that stays at the bottom (it costs about a seventh of a phone screen)?
5. ~~**"Ansehen" in the Mehr menu.**~~ Answered 2026-09-27: renamed "Zur Artikelseite". Leaving the form to look at the article is a common check. Is
   it fine folded behind "Mehr …", or should it be a visible quiet link?
6. ~~Datierung echo~~ Answered 2026-09-27: echo cut; one hint line plus a "?" popover.
7. **Create step.** Should "Neuer Artikel" stay two fields (Titel, Bestand) and then open the full
   form, or should it be the full form from the start? The two-step flow is what the app does
   today.

Chips moved into the system as `autocomplete` (2026-09-27): `system/autocomplete.js` + its CSS section.
