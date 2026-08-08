# Form wave — audit, directions, rulings

Status: DECIDED (owner rulings 2026-08-08 — verbatim in
`docs/requirements/owner-interview-2026-08.md`; section C below records how each
decision came out). Implementation wave in progress. The edit
surface is the next screen after the workbench, per the owner's priority ruling
("let's do this screen first. Learn from it and then we can apply the learned to
the other screens" — `docs/requirements/owner-interview-2026-08.md`).

Nothing in this file is law itself. Rulings land in `docs/requirements/`; cues and
cascade rules land in `design-review-law.md` — and only after an owner decision.

Renders behind this brief (owner artifact, 2026-08-08):
<https://claude.ai/code/artifact/f59d6a43-8f5c-447d-a9a5-268e13c23402>

## A. Audit of the current form (REAL renders, this commit)

Ranked by cost to the archivist; each names the law it fails.

1. **The screen ignores the desk** (Q9, ruling D "archivist surfaces
   desktop-first"). Byte-identical layout at 680 and 1440 px: one 52rem column,
   2058 px tall, half a desktop empty.
2. **Seven boxes for fourteen fields** (Q5, learning G.2). Each group draws a
   border plus a tab legend — the drawer-tab silhouette seven times on a screen
   whose sibling (the ledger) has no boxes at all.
3. **Three places to act** (G.9, C10). The sticky Speichern band, a second band
   under it for the lifecycle action, three text links per media row. The sticky
   band also covers the field beneath it while scrolling.
4. **Every input is the same width** (Q6, C11). An 8-character Signatur gets the
   same 745 px box as the Titel; width claims nothing about content.
5. **Publishing costs four interactions** (Q10): Veröffentlichen → preview panel
   → checkbox → Veröffentlichen, and the panel renders above the fold, so the
   archivist loses their place.
6. **"Beschreibung" is labelled twice** (Q2): section legend + field label.
7. **The browser speaks English**: the native file input's "Choose Files / No
   file chosen" sits inside the German media register.
8. **A different header** (precedent rule): no search, one lone "Zurück zur
   Suche" link — the edit screens do not inherit the approved chrome.

## B. The four compositions mocked (MOCK — real stylesheets, no product change)

All four render through the real token/cascade layer with the real corpus record
(Sommerfahrt 1962 / F12 / two media), so no judgment rides on thin test data
(G.6, H.7). Builder: kept in the session scratchpad, not the repo.

- **A · Der Bogen** — one sheet; sections separated by a rule and a margin
  label, never a box; a label column so values share one axis; two section
  columns appear intrinsically (multi-column flow, no width query, C11); field
  widths derived from the domain in `ch` (Signatur = 12ch because ≤ 8
  characters).
- **B · Werkbank** — the workbench frame reused: work column + THE sheet, where
  the sheet is the reader's view of this record, so exposure is permanently on
  screen and the publish preview step dies. Same 80rem switch as the pane.
- **C · Die Karteikarte** — the record as a catalog card: one ruled row per
  field, no box until worked on; rare sections folded WITH their values in the
  summary, so folding hides nothing.
- **E · C + B** (recommended) — the card in the pane frame. Whole record plus
  reader's sheet in 778 px at 1440; the pane leaves below 80rem.
- Supporting: the create step as a **doorway** (two fields on a sheet + a
  sentence naming what happens next), and a states render (rest / hover / edit /
  rejected / CAS conflict).

## C. Decisions (owner, 2026-08-08)

1. **E**, with A's two-column behaviour INSIDE the card — the card's sections
   break into two columns by grid, no guessed breakpoint.
2. **One sticky record row at the top.** The bottom footer band and the separate
   lifecycle band die.
3. **No title header** — every identity fact is a field.
4. **Folded rare sections, values in the summary.**
5. **Permanent exposure statement, one-click publish**; the preview gate dies.
6. **Icons for media rows**; arrow-up/arrow-down join the one icon set.
7. **Keep the NATIVE file input** (a German browser renders German strings) —
   this reverses my recommendation.
8. **C13 + C14 adopted as cascade rules.**

## D. Wave order (one writer)

1. Chrome: edit screens inherit the workbench header; the record row becomes the
   view's one control row (one `--control-height` knob).
2. Card: ruled rows replace the seven fieldsets; sections flow in a two-column
   grid (`repeat(auto-fit, minmax(<derived>, 1fr))`, C11 — the floor is computed
   from the label column + the value minimum, arithmetic beside the rule); folded
   rare sections with value summaries; the prose field grows with its content.
3. Sheet: reader's view + exposure statement, server-rendered, refreshed on
   save; the publish preview page retires.
4. Media: icon toolbar per row (two new glyphs). The native file input STAYS
   (owner ruling 7).
5. Guards: the control-row and overlay walkers cover the new row for free; add a
   computed proof that the card's state rules outrank its resting defaults (the
   C13 bug, caught by a test rather than an eye).

Explicitly NOT in this wave: the detail reader (cover eats the first viewport,
date rendered twice — C7), the confirm surfaces, and issue #42's unimplemented
rulings.
