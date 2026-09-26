# Design rules — draft (2026-09-26; sizes, serif, media rules owner-answered)

Base: round-2 direction A (Druckschwarz) for start and list, C (Schaufenster) for the article
page when a square preview exists. Goal: rules strict enough that one writer can build one
component, another one layout, and the pages come out as one piece.

The mechanisms of `docs/design/design-review-law.md` stay (catechism, cue register, cascade
rules, owned components from Wave C). These rules replace its *contents*.

## 1. Method (every screen, every element)

1. Write the screen's job first: who, what they try to achieve, success (SCREEN-JOBS.md).
2. Price every element: cost (attention, size, reading) against gain for those users.
   High cost + low gain → cut. Visual weight follows gain, never build order.
3. Price again per screen size (rule 2). An element worth its space on a desktop can be too
   expensive on a phone.

## 2. Space budget — three sizes

Sizes are container widths, not device names: **S** < 40rem (phone), **M** 40–80rem,
**L** ≥ 80rem (large desktop).

Every component declares one of four renderings per size:

| Rendering | Meaning |
| --- | --- |
| full | its whole form |
| compact | same job, less space (a list instead of a chart, one line instead of a block) |
| folded | behind one disclosure the user opens on purpose |
| absent | not on this size at all |

Who is where (owner): archivists work mostly on large screens, members and link-holders mostly
on small ones. L is tuned for archivist work (density, side columns, bulk actions); S is tuned
for finding and viewing (search, results, one article).

S-rules:
- Start page on S: search, plus "Meine Entwürfe" for archivists. Nothing else — browsing
  (Bestände, Zeitleiste) happens on the Archiv page's folded "Filter".
- One column. One primary task per screen, and it is on the first screen.
- Navigation aids that are really filters (Bestände, Zeitleiste, Typ) are **folded** into one
  "Filter" disclosure — never open by default.
- No side-by-side compartments, no charts, no placeholder areas.

L may spend spare width on balance (e.g. the Zeitleiste as a thin-bar list in a side column),
as long as it stays easy to read. M behaves like L minus the side column.

Example: Zeitleiste — L full (thin-bar list, side column) · M compact (decade links in one
row) · S folded (inside "Filter").

## 3. Tokens

- **Color:** white ground, black ink, one secondary ink (text only), a hairline gray, the heavy
  rule (ink, ~6px), error red. No other hue. No gray fills. The dark theme is the same tokens
  inverted; nothing is designed dark-only. The one exception: the "Anmelden mit DPB Login"
  button is solid dark gray (owner ruling).
- **Type:** three families, five roles.
  - Serif small caps: the wordmark only.
  - Serif: section headings and article titles (owner). Lists, body, buttons: sans.
  - Sans: everything else (body, labels, links, buttons).
  - Mono: Signatur, Datierung, counts (tabular figures).
  - Roles: display (article title) · heading (section) · body · meta · label. No ad-hoc sizes.
- **Counts:** never at display size. Small, secondary ink, beside their label, or dropped.
- **Spacing:** the existing 4px scale; more space above a heading than below it.

## 4. Layout primitives (few, composable)

| Primitive | Rule |
| --- | --- |
| Page | masthead + one main column; content never wider than the reading measure unless it is a table |
| Section | opened by one heavy rule; serif heading left, at most one action link right; nothing boxed |
| Split | main + side column at L; at M/S the side column moves below or folds (component decides) |
| Pair | two sections side by side at L/M; stacked at S |

## 5. Components (one writer each, built in the component gallery first)

| Component | Job | L / M / S |
| --- | --- | --- |
| Masthead | wordmark, nav (Archiv · Bestände · Erfassen), account | full / full / compact (wordmark + menu) |
| Search field | the main entry | full / full / full |
| Section head | rank + one action | full / full / full |
| Register list | ruled rows: label left, quiet figure right (Bestände, decades, lists) | full / full / compact |
| Ledger | hairline result table | full / full / compact (title line + one meta line) |
| Facts | definition list; order: Datierung, Ort, Urheber, Typ, Bestand, then quiet Standort, Signatur | full / full / full |
| Media | square preview of the first image, or of a PDF's/scan's first page; otherwise no media block, files as a list | full / full / full (first on S) |
| Onward | "Mehr aus diesem Bestand / Jahrzehnt" | full / compact / compact |
| Filter | active filters (removable) + options | full side column / row / folded |
| Mark | Entwurf (outline), "später" (dashed) | same everywhere |
| Buttons | primary solid black, secondary outline, SSO solid dark gray | same everywhere |

## 6. Article page rule (media decides the layout)

- Square image preview exists → C's layout: media large left, title + facts right (S: media
  first, full width).
- PDF or scan → its first page, rendered as the square preview (owner). Needs thumbnail
  generation for PDFs — today PDFs show empty tiles (owner's UI-pass item 1).
- No renderable medium (audio, object without photo, no files) → single column like A: title,
  facts, Beschreibung, file list. No placeholder frame.

## 7. Order of work (divide and conquer)

1. Owner rules on this draft → it replaces the contents of `design-system.md` and the
   DESIGN.md digest.
2. Tokens (one writer): the monochrome retoken in `tokens.css`.
3. Components (one writer each, in parallel where files are disjoint), rendered in the
   component gallery at S/M/L before any page uses them.
4. Layouts, then pages (start, list, article, door), each checked against its SCREEN-JOBS
   table.
