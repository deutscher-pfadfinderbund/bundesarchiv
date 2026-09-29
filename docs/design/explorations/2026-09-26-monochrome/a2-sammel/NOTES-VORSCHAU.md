# a2-sammel — the preview pane ("Vorschau"), three variants

Page: `vorschau.html` (`?v=spalte|rand|zeile`, `&offen=BA 587` opens a record). CSS `vorschau.css`,
behaviour `vorschau.js` (mock only). Media are placeholders: no archive file is committed.

Owner ruling 2026-09-29: the pane is an extra, shown only where there is room next to the list,
never a column that squeezes the list.

## Screen job

Who: archivists, weekly, on L with a pointer; members browsing now and then. Job: look at one
record well enough to decide (is this the one? is its data right? does the scan match the title?)
without losing the place in the list, then go to the next one. Success: the next record is one key
away, and the list never gets narrower or loses its place.

The app has a pane today (`_pane.html`, `?artikel=<ulid>`). It narrows the list to make room for
itself. That breaks the ruling.

## The three variants

| | Spalte (mode) | Rand (margin) | Zeile (unfold) |
| --- | --- | --- | --- |
| Where | a column right of the page; the page moves to the start edge | the free margin right of the centred page | a band under the row, across the ledger |
| Shown from | ≥ 105rem (~1680 px); pane 22–40rem | ≥ 124rem (~1980 px); pane 20–28rem | every size from M |
| How it opens | "Vorschau" in the tool row, next to "Spalten …" (a preference, kept in a cookie) | a row's "Vorschau" (hover), or a click on the row | a row's "Vorschau", or a click on the row |
| Next record | ↑ ↓ | ↑ ↓ | ↑ ↓ (the band moves) |
| Cost | the list moves to the start edge once, when the mode is switched on | none; but at 1920 px there is no room, so most screens never show it | rows below move down; repeats Signatur, Typ and Datierung from the row |
| Gain | the largest preview (PDF page ~37rem tall at 1920 px); the list stays put while stepping | zero layout change | works on laptops (1440 px), where neither side variant fits |

Recommendation: **Spalte.** It is the only one that shows a scan large enough to judge on a common
wide screen (1680–1920 px), and its one cost (the list moving to the start edge) happens only when
the archivist asks for it. Rand never appears on a 1920 px screen. Zeile is the fallback if the
archivists mostly work on laptops, but then the pane is no longer "an extra next to the list".

## Shared parts (all variants)

- Content, in reading order: title (subhead serif; a title in a side column takes a lower rank),
  the first file (an image in its own shape, or a PDF's first page, portrait; absent without files)
  with the Digital words under it, the byline (Signatur · Typ · Datierung · Ort · von Urheber), the
  quiet facts Bestand and Standort (Standort for archivists only), "Öffnen" (primary) and
  "Bearbeiten" (archivists), then the keys note "↑ ↓ nächster Artikel · Esc schließt".
- No frame: the pane is a column of the page, not a floating panel. Its title stands level with the
  search sentence; space sets it apart from the list.
- The row in the pane: its title in bold and its two rules in ink. This is the one place the list
  says "this one", because with the arrow keys the archivist no longer points at it.
- Controls that can never become active are hidden: the toolbar's "Vorschau" and the rows'
  "Vorschau" links exist only where the variant can show.
- Without JS: the row's "Vorschau" link is a plain GET (`?artikel=<ulid>`, as today), and the
  server renders the pane. The arrow keys are an enhancement.

## Open questions for the owner

1. Which variant: Spalte (recommended), Rand, or Zeile?
2. Spalte: should the page stay at the start edge while the mode is on, even when the pane is
   closed? The mock moves it only while a record is open.
3. The Bestand fact repeats a Bestand the search sentence already filters by. Drop it in that case?
4. Should members get the pane too? Their job is browsing, not checking, and the title already opens
   the article.
