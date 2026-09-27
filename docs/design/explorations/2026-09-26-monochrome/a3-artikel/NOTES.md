# a3-artikel: article page (archivist view), delete confirm, Bestand forms

Pages: `artikel.html` (BA 1784, photo album, direction C), `artikel-video.html` (BA 1035,
DVD, one column), `artikel-entwurf.html` (BA 1784 shown as an Entwurf, a mock state),
`loeschen.html`, `bestand-neu.html`, `bestand-bearbeiten.html`. Built from `../system/system.css`
plus `a3-artikel.css` (four small additions, listed at the end).

Mock content, not from `data.json`: both Beschreibung texts, the DVD's file
(`bundeslager-2007.mp4`), the five pages of the album, the Entwurf state, Bund's Sichtbarkeit
("Alle Mitglieder"). Top-bar links point at `../r4-system/` because this folder has no start or
list page.

## Artikel: archivist view

Job: an archivist opens one record to check it, correct it, or finish it. Success: they see the
thing and its facts at once and reach Bearbeiten in one click. The same page is the members' and
link-holders' landing page. They get the same page without the action row.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Square lead preview (left, L) / first (S) | mid | highest: the thing itself | keep, large (direction C) |
| Further pages as square thumbnails under the lead | low | mid: shows how much there is, opens each page | keep; replaces the real "Weitere Aufnahmen · Blatt 1 / N" heading, since the thumbnails already say it |
| Crumbs (Bestand) | low | mid: the place plus a way to the scoped list | keep |
| Title | low | high | keep, the largest text |
| Datierung prose under the title (real `datierung_prose`) | low | none: the Datierung fact sits right below | cut |
| Bearbeiten (outline button) | low | high for archivists | keep, first under the title |
| "Weitere Aktionen …": Kopieren, Als Entwurf zurückziehen, Löschen | low when folded | low to mid: rare actions | folded into one menu. Opened on purpose, so the fold is allowed |
| Facts: Datierung, Ort, Urheber, Typ, Bestand (link) | low | high | keep, in this order |
| Standort, Signatur (quiet) | low | high for archivists | keep, last, one tier quieter |
| "Nur intern" after Standort (real) | low | low: the archivist knows; members never see the row | cut (no role labels) |
| Beschreibung | mid | high when present | keep, labelled, after the facts; absent = nothing |
| Umfang, Schlagworte, Weitere Angaben (real, optional) | low | mid | not rendered: the sample data has none. Suggested slots: Umfang after Typ, Schlagworte as a wide row after Bestand, Weitere Angaben as quiet rows after Standort |
| "Zurück zur Suche" (real) | low | none: browser Back keeps the search | cut (navigation ruling) |
| Onward: Mehr aus diesem Bestand / Jahrzehnt | low | mid for archivists, high for members | keep, three rows each |

Per size: L has media and facts side by side. S shows media first at full width, then crumbs,
title, actions, facts in two columns, Beschreibung, and the onward lists stacked.

### Artikel ohne Medien

Job and elements as above. Changes: no media block and no placeholder frame. The title is the
focus. Facts use four columns. Beschreibung takes half the width, which keeps its lines short.
A "Dateien" register lists the files that cannot be previewed (name left, kind and size right).
The Dateien heading costs mid for a single row. It pays off once an article has several files.

### Artikel als Entwurf

Job: the archivist sees at once that this record is not public yet, who will see it once it is
published, and how to finish it.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| "Entwurf" mark after the title | low | high: the one state signal | keep; the words only, no box |
| "Nach Veröffentlichung sichtbar für: Alle Mitglieder." | low | high: the audience before the click (ruling 5) | keep; real wording from the exposure statement |
| Veröffentlichen (outline button, next to Bearbeiten) | low | mid: names the next step; it links to the edit form like Bearbeiten does | keep (real); see open question 2 |
| Als Entwurf zurückziehen | none here | none | absent: it can never become active on a draft |

"Bearbeiten" is in the same place in both states: first in the row under the title.

## Löschen (confirm)

Job: the archivist confirms that this record is the one to delete and understands what goes.
Success: one deliberate click or a way out.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Crumbs (Bestand) | low | low to mid: the place | keep (ruling: crumbs on form pages) |
| "Artikel löschen?" | low | high | keep |
| Title + quiet Signatur (links back to the article) | low | high: which record | keep (Signatur budget point 3) |
| Consequence sentence: the catalogue entry with all its details, its 5 files, no bin, not undoable | low | high | keep; names the files, not only a count of records |
| "Artikel und 5 Dateien löschen" (red) | high by design | high | the one red button; its label names the full consequence |
| Abbrechen | low | high | keep, outline |
| The framed panel (real `.panel`) | mid | none: the column already groups it | cut |

Draft variant (real `?verwerfen=1`): same page, "Entwurf verwerfen?" and "Entwurf und 5 Dateien
verwerfen". Not drawn.

## Neuer Bestand

Job: add a place in the tree. Success: a name, a parent, done.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Title "Neuer Bestand" | low | high | keep |
| Name (autofocus) | low | high | keep |
| Eltern-Bestand (select, "Oberste Ebene" first) | low | high | keep; the real "— Oberste Ebene —" loses its dashes |
| Sichtbarkeit (select, "Vom Bestand erben" first) | low | mid | keep |
| Gruppen + hint (only for "Gruppe(n)") | mid: shown although usually unused | low to mid | keep visible (real; a field that can become active is not hidden) |
| Anlegen (primary) | low | high | keep, first so Enter submits |
| Abbrechen | low | mid: replaces the header's "Zurück zur Suche" | ADD; the way back sits where the decision is |

## Bestand bearbeiten

Job: rename a Bestand. Moving it and changing Sichtbarkeit come later.

| Element | Cost | Gain | Verdict |
| --- | --- | --- | --- |
| Name (autofocus, prefilled) | low | high | keep |
| Hint: "Der neue Name gilt sofort für alle 463 Artikel in diesem Bestand." | low | mid: the consequence of a rename | ADD (the save reindexes the whole subtree) |
| Eltern-Bestand, Sichtbarkeit (read-only facts) | low | mid: context | keep, as `facts` |
| "Verschieben und Sichtbarkeit ändern folgen später." | low | mid: why those two cannot change | keep, quiet |
| Speichern (primary) + Abbrechen | low | high | keep; Abbrechen replaces the header back link |
| Crumbs | none | none for a top-level Bestand (no parent) | absent here. A sub-Bestand would show its parent chain |
| "Inzwischen geändert" (conflict state, real) | — | high when it happens | not drawn. Proposal: one quiet sentence above Name ("Ein anderer Bearbeiter hat diesen Bestand inzwischen gespeichert: jetzt „…“. Bitte prüfen und erneut speichern."), no frame, no red ("Conflict is not an error") |

The validation error state (`field-error`, red underline) exists in CSS but is not drawn.

## Rules whose boundary I hit

- **No role labels.** A draft still has to say who sees it. I used the exposure wording "Nach
  Veröffentlichung sichtbar für: …", which says who will see it and not who sees it now. I cut
  "Nur intern" after Standort for the same reason.
- **Hide a control only if it can never become active here.** "Als Entwurf zurückziehen" is absent
  on a draft because it can never become active there. The Gruppen field stays visible because it
  becomes active with "Gruppe(n)".
- **Frames only for cohesion.** The media placeholders and the input focus ring are the only
  frames. The confirm panel's frame is cut.
- **Split at M.** `split` keeps the two columns while both fit `--column-min` (18rem). Around
  800px wide, the title column is about 15rem and a 3rem title breaks into many lines. The layout
  has no knob for this.

## Known leftovers (after the one fix batch)

- At L the square lead and its thumbnails sit further apart than `--space-3`. The plate stretches
  to the height of the taller facts column, and the grid spreads the extra height over its row
  gap. Fix in the component: `align-content: start` on `.plate`.
- At S the Signatur on the delete page wraps ("BA / 1784") beside a two-line title, because the
  `register-figure` may wrap. Fix: `white-space: nowrap` on the figure, or put the Signatur on
  its own line.
- The title of BA 1784 breaks at its hyphens into four lines in the right column at L. That is
  acceptable for the lead, but it is long.

## Proposed system additions (`a3-artikel.css`)

1. **`plate` component** (knob `--plate-columns`). Job: a square lead preview across the whole
   column, with the other pages as square thumbnails beneath it (direction C). Why not `media`:
   `media`'s lead spans 2×2 of 4 columns at 4:3, so in the left column it is half as wide and not
   square. `media` has no knobs. Better long-term: fold it into `media` as two knobs (lead span,
   lead ratio) instead of keeping two components.
2. **`field` component** (knob `--field-size`). Job: label over control, with a hint or error
   under it; a select gets the same underline as an input (`appearance: base-select`, native
   picker). The system has no form field, and every form screen needs one.
3. **`button-danger` variant** (worn with `button-primary`). Job: the one red button on confirm
   surfaces. It only re-points the button's `--ink` to `--error`.
4. **`row` layout** (knob `--row-gap`) and **`column` layout** (knob `--column-size`, default
   `--measure-search`). Jobs: an action row (buttons and a menu side by side, wrapping), and one
   narrow column for forms and confirm surfaces so lines stay short. `stack` only stacks, and
   `page` is the full measure.

## Open questions for the owner

1. Delete: should the page say that the admin's Nextcloud bin may still hold the files for a while,
   or would that promise a recovery that the app does not control? Right now it says there is no
   bin and that it cannot be undone.
2. Draft: "Veröffentlichen" and "Bearbeiten" open the same edit form, where saving is publishing.
   The article page now shows the audience line itself. Should Veröffentlichen publish directly
   from here (one click, audience already shown), or should the two buttons merge into one?
3. Should a published article also show its audience to archivists ("Sichtbar für: Alle
   Mitglieder") as a quiet line? Today only drafts and the edit form say it.
4. Where does "Bestand bearbeiten" start from? Today it is a "+ Neu …" menu entry when the list is
   scoped to one Bestand. That is a create menu. A quiet link in the list's search sentence when
   one Bestand is set would be the proposal.
5. You ruled that a Bestand may have an optional description (2026-08-22), but the real forms do
   not have the field yet. Should it be in these two forms now?
6. Rare actions (Kopieren, Zurückziehen, Löschen) are folded behind "Weitere Aktionen …". Is one
   click more acceptable for archivists, who come weekly, or should these three be quiet links
   in the row?
