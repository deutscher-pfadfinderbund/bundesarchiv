---
name: Bundesarchiv
description: The DPB archive as a well-set printed catalogue. Black ink on white paper, type carries the order.
colors:
  # Light-mode values. Dark values and the light-dark() pairs live in .impeccable/design.json
  # colorMeta. NORMATIVE SOURCE until the retoken wave: the mock system,
  # docs/design/explorations/2026-09-26-monochrome/system/system.css (@layer tokens).
  # After it: src/bundesarchiv/app/web/static/tokens.css. Change colors there, never here.
  paper-white: "#ffffff"
  print-black: "#000000"
  secondary-ink: "#595959"
  quiet-ink: "#767676"
  hairline: "#dcdcdc"
  control-edge: "#8f8f8f"
  faint: "#d0d0d0"
  band-black: "#000000"
  band-ink: "#ffffff"
  band-secondary-ink: "#b3b3b3"
  correction-red: "#c4000b"
typography:
  wordmark:
    fontFamily: "ui-serif, Iowan Old Style, New York, Charter, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.12em"
    fontFeature: "small-caps"
  title:
    fontFamily: "ui-serif, Iowan Old Style, New York, Charter, Georgia, serif"
    fontSize: "3rem"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.01em"
  heading:
    fontFamily: "ui-serif, Iowan Old Style, New York, Charter, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  subhead:
    fontFamily: "ui-serif, Iowan Old Style, New York, Charter, Georgia, serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  entry:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1.1rem"
    fontWeight: 400
    lineHeight: 1.35
  query:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 400
    lineHeight: 1.4
  body:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 600
    lineHeight: 1
  meta:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.3
  note:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 400
    lineHeight: 1.3
  data:
    fontFamily: "ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
rounded:
  none: "0"
spacing:
  space-1: "0.25rem"
  space-2: "0.5rem"
  space-3: "0.75rem"
  space-4: "1rem"
  space-5: "1.25rem"
  space-6: "1.5rem"
  space-7: "1.75rem"
  space-8: "2rem"
  space-9: "3rem"
  space-10: "5.5rem"
components:
  button-primary:
    backgroundColor: "{colors.print-black}"
    textColor: "{colors.paper-white}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0.75rem 1.25rem"
  button-primary-hover:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.print-black}"
  button-secondary:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.print-black}"
    typography: "{typography.control}"
    rounded: "{rounded.none}"
    padding: "0.75rem 1.25rem"
  button-secondary-hover:
    backgroundColor: "{colors.print-black}"
    textColor: "{colors.paper-white}"
  field-input:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.print-black}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0.5rem 0.75rem"
  chip:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.print-black}"
    typography: "{typography.meta}"
    rounded: "{rounded.none}"
    padding: "0 0 0 0.5rem"
  menu:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.print-black}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "0.5rem 0"
  topbar:
    backgroundColor: "{colors.band-black}"
    textColor: "{colors.band-ink}"
    typography: "{typography.meta}"
    height: "4.25rem"
  note:
    textColor: "{colors.quiet-ink}"
    typography: "{typography.note}"
---

# Design System: Bundesarchiv

This file is the visual digest. The binding law is `docs/design/design-system.md` (principles
with their reasons, tokens, components) and `docs/design/design-review-law.md` (how a change is
reviewed, which cues are licensed). The mock system that proves both lives in
`docs/design/explorations/2026-09-26-monochrome/system/` (`system.css`, `gallery.html`,
`icons.svg`, `autocomplete.js`).

## Overview

**Creative North Star: "Druckschwarz"**

The archive looks like a well-set printed catalogue: black ink on white paper, and nothing a
printer would not have. Type carries the order. Alignment and space make the structure, so lines
are rare: a hairline appears only where a row has two ends that the eye must connect, and a frame
only where things have no natural line between them (an input's edge, a chip). There is no second
hue, no gray fill, no shadow, no rounded corner. Red is the only colour, and it means "this is
wrong" or "this is about to remove something".

It is a working tool first. Archivists, the most important users, catalogue weekly on large
screens; members read on phones. The look serves both by being quiet: every element is priced by
what it costs the reader against what it gives them, and anything that signals what the user
already knows is cut. The wordmark (small-caps serif) is the one flourish and stays. Dark mode is
tuned, not inverted: no pure black or white, and lines are quieter because bright lines smear on
black.

Rejected on purpose: beige or "warm AI" palettes, violet, gray chrome and gray fills, scout
costume, mono capitals as a label voice, decorative lines, dashes as separators.

**Key Characteristics:**
- Two inks: black for content, one secondary gray for text only.
- Serif only for the wordmark, section headings and article titles; sans for everything else;
  mono only for data in columns.
- Square corners everywhere; flat surfaces; one focus ring (3px ink).
- Lines connect a row's two ends; they never separate.
- Red only for errors, conflicts and removing controls about to act.
- Every element priced (cost against gain) per screen size S / M / L.

## Colors

A monochrome palette: two inks on paper, three grays with one job each, and one red.

### Primary
- **Print Black** (#000000): all content text, headings, the primary button's fill, the focus
  ring, the active option in a suggestion list (inverted: black ground, white text).

### Neutral
- **Paper White** (#ffffff): the page ground and every floating panel (menu, popover, suggestion
  list), even when their button sits in the black band.
- **Secondary Ink** (#595959, 7:1): secondary text only: labels, hints, asides, meta lines,
  crumbs, quiet icons. Never a fill, never a line.
- **Quiet Ink** (#767676, ≥4.5:1): the quietest text, the note beside a label or heading
  ("intern").
- **Hairline** (#dcdcdc, ~1.4:1): the one connecting line, drawn only between the two ends of a
  row. Too faint to be an affordance on purpose.
- **Control Edge** (#8f8f8f, ≥3:1): the edge of an input, a chip box, a floating panel. An
  affordance, so it meets the 3:1 non-text contrast floor; it is not a connector.
- **Faint** (#d0d0d0): present but inactive: disabled arrows, the placeholder cross of an item
  without an image. Tuned brighter in dark, where the hairline would vanish.
- **Band Black** / **Band Ink** / **Band Secondary Ink** (#000 / #fff / #b3b3b3): the top bar, an
  inverse band on light. In dark it becomes the page with an edge.

### Semantic
- **Correction Red** (#c4000b light, #ff6b61 dark): field errors and conflicts (a doubled edge),
  the conflict notice's heavy rule and heading, a removing control on hover, press and focus, the
  committing button of a delete confirm.

### Named Rules
**The Two-Ink Rule.** Black carries content, one gray carries secondary text. Gray never fills a
surface and never draws chrome.

**The Red Acts Rule.** Red appears only where something is wrong or something is about to be
removed. Not for warnings, not for emphasis, not for decoration.

**The Tuned Dark Rule.** Dark mode re-points the same roles with its own values (#0b0b0b ground,
#f0f0f0 ink); nothing is designed dark-only, and nothing is a plain inversion.

## Typography

**Display Font:** the system serif (ui-serif, Iowan Old Style, New York, Charter, Georgia)
**Body Font:** the system sans (system-ui, -apple-system, Segoe UI, Roboto)
**Data Font:** the system mono (ui-monospace, SF Mono, Menlo, Consolas), tabular figures

**Character:** a bookish serif for rank and a neutral sans for work. The serif appears rarely,
so each appearance means "a new section" or "this record".

### Hierarchy
- **Wordmark** (small caps 600, 1.5rem, tracking 0.12em): the top bar's "Bundesarchiv" only.
- **Title** (serif 700, 3rem / S 2rem, 1.08): the page h1: the article title, the start heading.
  On the edit form the title is itself the input (see Components).
- **Heading** (serif 700, 2rem / S 1.6rem, 1.1): section h2.
- **Subhead** (serif 700, 1.35rem, 1.25): secondary sections (the form's sections, onward lists).
  A title in a side column takes the heading role.
- **Entry** (sans 400, 1.1rem, 1.35): the lead of a list row.
- **Query** (sans 400, 1.25rem / S 1.1rem, 1.4): the search sentence and the large search field.
- **Body** (sans 400, 1rem, 1.5): running text, inputs; prose at most 65ch.
- **Control** (sans 600, 0.95rem, 1): buttons and pager steps.
- **Meta** / **Label** (sans 400, 0.9rem): asides, column heads, crumbs, hints / field and fact
  labels, mixed case.
- **Note** (sans 400, 0.8rem, Quiet Ink): an annotation touching its label or heading.
- **Data** (mono 400, 0.9rem, tabular): counts, dates, Signaturen, when they stand in a column.

### Named Rules
**The Serif Rank Rule.** Serif marks rank: the wordmark, section headings, article titles.
Lists, body, labels and buttons are sans.

**The Mono Column Rule.** Mono only for values that align in a column. A single date or Signatur
in running text or a fact list is sans.

**The One Role Rule.** Every text node uses exactly one type role. An ad-hoc size or weight is a
defect; counts never appear at display size.

## Layout

One main column capped at 80rem (content box ~74rem), a 3rem gutter (S: 1rem). Space is the main
structural tool: section gap 5.5rem (S: 3rem), block gap 2rem, a head sits 1rem above its content
so it belongs to it, rows pad 0.75rem. The 4px scale (`space-1` … `space-10`) is the only source
of distances.

Three sizes, judged on the container: **S** < 40rem (phone), **M** 40–80rem, **L** ≥ 80rem. Every
component declares per size one of: full, compact, folded (behind a disclosure opened on
purpose), absent. S is tuned for finding and viewing (one column, one task, filters folded);
L for archivist work (side columns, a sticky form margin, bulk actions). Type size follows the
viewport, not the container, so a heading keeps its rank in a narrow column.

Destinations are few: start, one list, article, forms, door. Everything else (a Bestand, a decade,
a search, "Meine Entwürfe") is a preset of the one list. The list's heading is a search sentence:
"Suche [Feld] in Gruppen des DPB · alle Jahrzehnte · jeder Typ + Filter". Breadcrumbs show the
place ("Archiv › Bund").

### Named Rules
**The Alignment-First Rule.** Structure comes from alignment and spacing. Draw a line only where
no natural line appears.

**The Two-Ended Line Rule.** A hairline ties a row's two ends so the eye does not slip. Never above
the first or below the last row, never under headers or filter bars.

**The Priced Element Rule.** Every element, and every fix, is priced (attention, size, reading)
against its gain for these users, per size. High cost and low gain: cut.

## Elevation & Depth

Flat. There are no shadows at rest and none in motion. Floating panels (the menu, the ⓘ popover,
the suggestion list) are page surface with a Control Edge border, placed in the top layer by the
native popover; the edge, not a shadow, separates them. Focus is the one depth-like cue: a 3px
Print Black outline, offset 3px; where an underline is the field (the title field, the compact
search), focus thickens that underline to 3px instead.

### Named Rules
**The Flat Rule.** No shadow, glow, gradient or blur anywhere. Separation comes from an edge or
from space.

## Shapes

Square corners everywhere (radius 0): buttons, inputs, chips, panels, thumbnails. Lines are 1px
(the heavy notice rule is 3px). Frames are rare and each earns its place: an input's edge, a chip,
a floating panel, a placeholder tile. An item without an image draws a thin cross in Faint inside
its tile. There is no bevel, no pill, no circle; the help mark is the text character ⓘ.

## Components

### Buttons
- **Shape:** square (0), padding 0.75rem 1.25rem, Control type, 1px ink border.
- **Primary:** solid Print Black, white text; hover inverts to outline. One per surface (Speichern,
  Anlegen, Suchen, the door's login).
- **Secondary:** outline, ink text; hover fills.
- The door page's "Anmelden mit DPB Login" is a primary button (owner 2026-09-27: no gray fill).
- **Add ("+ …"):** not a framed button: a plain meta-size text control starting with "+"
  ("+ Angabe hinzufügen", "+ Dateien hinzufügen", the top bar's "+ Neu …"); underline on hover.
- A `label` styled as a button (file chooser) gets the pointer cursor from the component.

### Inputs / Fields
- **Style:** label above in Label type, Secondary Ink; the control has a 1px Control Edge, Paper
  White ground, 0.5rem 0.75rem padding, one height for inputs and selects.
- **Focus:** the 3px ink ring. **Hover:** edge turns ink.
- **Error / conflict:** `aria-invalid="true"` doubles the edge in Correction Red (border plus a
  1px inset), with the message or "Inzwischen gespeichert: …" under the field.
- **Markers:** "*" after a required label, in the label's own ink; the note "intern" after a field
  or heading shown only to archivists. The minority is marked, never the rule.
- **Hint:** one line at most, Secondary Ink; details go behind an ⓘ that opens a popover.
- **Textarea:** at least N lines (`min-block-size` in `lh`), grows with its text where
  `field-sizing: content` works.
- **Title field:** the page h1 is the record's title, editable in place: no label, no frame, a
  hairline under it on hover, a 3px underline on focus, the placeholder "Titel" while empty.

### Autocomplete (signature component)
- **Single:** a text field that suggests from a list; free text stays allowed (Medienart,
  Dokumenttyp, the Feld of Weitere Angaben).
- **Multiple:** chosen values become square chips inside one field edge (a hairline frame, meta
  type, a removing ×), then the typing input. Enter or comma adds, Backspace removes the last,
  pasted lists split, pending text is added on leaving the field (Schlagworte, Gruppen).
- **Suggestions:** a Paper White list with a Control Edge; the active option inverts (black
  ground, white text).
- Without JS it is the plain input with the native datalist; the server contract is the comma list.

### Remove
- One × for every removal (media rows, Weitere Angaben rows, chips): Secondary Ink at rest, ink
  on hover. It carries the **danger** context, so that ink turns Correction Red on hover, press and
  focus. Where it deletes for good it also asks first (`hx-confirm`; without JS the server's
  two-step).

### Menu
- A text button ending in "…" opens a native popover list: Paper White, Control Edge, rows of
  links or buttons, underline on hover. Anchored under its button, right edges aligned. A
  destructive entry ("Löschen") carries the danger context.

### Contexts, not variants
- `.quiet` makes a fact, a register row or a whole section one tier quieter: it re-points the ink
  to Secondary Ink and draws its own text in it (Standort and Signatur in the facts, a compartment
  that comes "später", the set-apart "Unbekannt" row).
- `.danger` on any action that deletes for good re-points the ink to Correction Red while it is
  about to act (hover, press, focus). It sets no property itself, so a button, a ×, a menu entry or
  a link turns red without a variant of its own. There is no danger button.

### Navigation
- **Top bar:** Band Black, 4.25rem, the wordmark left; right: "+ Neu …" (archivists) and
  "Abmelden". No account name, no browse items.
- **Crumbs:** meta type, Secondary Ink, underlined links, "›" between steps, first step "Archiv".
- **Search sentence:** the list's heading; set filters in ink, open ones quieter, centre dots
  between them.

### Register and Ledger
- **Register:** ruled rows, label left, quiet figure right; a hairline only on rows with two ends.
- **Ledger:** the result table in hairlines; one lead per row (the title in Entry type), facts one
  tier quieter; the sort arrow on the active column is the only sort feedback.

### Record margin (form)
- The form's margin (sticky at L): the conflict notice when there is one (a 3px red rule, a red
  subhead, one sentence with the changed fields as links), then "Status", "Sichtbar für" (the
  inherited option names its value; Gruppen appears only for "Bestimmte Gruppen"), Speichern with
  "Mehr …", and the version line.

### Note and Mark
- **Note:** Note type in Quiet Ink, touching what it qualifies ("Standort intern").
- **Mark:** a state in words, Label type, Secondary Ink ("Entwurf", "Titelbild"); never a box.

## Do's and Don'ts

### Do:
- **Do** let alignment and the space scale make the structure; draw a hairline only on a row's two
  ends.
- **Do** price every element and every fix per size (S / M / L); cut high cost, low gain.
- **Do** inherit: a part sets only what differs from its context. A marker or icon inside text
  takes the text's colour and size.
- **Do** keep controls with their state: the result range in the pager, the sort direction in the
  column head, the audience in "Sichtbar für".
- **Do** keep paired controls visible and disabled when inactive (Zurück / Weiter, the end arrows),
  drawn in Faint.
- **Do** make every icon-only control name itself (`aria-label`); icons come from the one set.
- **Do** use centre dots to separate items in a line.

### Don't:
- **Don't** add a second hue, a gray fill, gray chrome, violet, beige or any "warm" tint.
- **Don't** use shadows, gradients, rounded corners, pills or bevels.
- **Don't** label roles ("nur Archivare"), mark what a list title already says, or place off-topic
  actions.
- **Don't** signal what the user already knows (no highlight for the column they just sorted).
- **Don't** hide a control that can become active on this page.
- **Don't** set labels in mono capitals, and don't use mono outside columns of data.
- **Don't** frame an add action or draw a line that separates instead of connects.
- **Don't** show counts at display size.
- **Don't** use dashes as separators.
