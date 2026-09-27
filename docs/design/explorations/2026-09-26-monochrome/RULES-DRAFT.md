# Design rules — draft (2026-09-26; sizes, serif, media rules owner-answered)

**Superseded 2026-09-27** by `docs/design/design-system.md` (the law), `docs/design/design-review-law.md`
(cue register) and `DESIGN.md` (the digest). Kept as the record of how the rules came about.

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

4. Price the fix too. A fix is a new element or a new signal, with its own cost. If the fix
   costs more than the problem, keep the problem.
5. Every rule states intention · gain · cost · boundary. A rule without its reason gets applied
   where it hurts.

### Principles (owner, taught 2026-09-26/27)

| Rule | Intention | Gain | Cost | Boundary |
| --- | --- | --- | --- | --- |
| **Alignment gives structure** | With good spacing and alignment, content forms natural lines; the eye follows them without effort | simple on the eye, few objects | needs one strict grid and spacing scale | where no natural line appears, draw one (next rows) |
| **A line connects or anchors** | Ties two ends of a row so the eye does not slip across a long gap | eye stays on the row | each line is an object; many add up to noise | not above the first / below the last row, not under headers or filter bars — there the edge is spacing |
| **Frames highlight or create cohesion** | Where elements have no natural line between them (card: title top left, actions bottom right), a frame gives them something that connects them | the group reads as one | a frame is the loudest line; frames where alignment already groups are noise | not for grouping things that already stand together |
| **Heavy rules shape blocks** | They make sections read as blocks | strong structure | loud, bloom in dark, duplicate heading + space | removed (experiment `r3-linien/`): then spacing must carry the blocks and be much stricter |
| **One lead per row; facts one tier quieter** | Rows are scanned for the title; facts are read once a title catches | calm, fast scanning | none that matters: good-enough contrast is enough to scan a quieter column when focusing on it | no step-up for the sorted column — see next row |
| **Don't signal what the user already knows** | A change in appearance says "something important happened"; the user who sorted already knows | no noise from the user's own action | — | the sort arrow on the active column is enough feedback |
| **Mono only for data in columns** | Fixed-width digits align, rows of values scan | a typeface with one meaning | fewer tools for labels | values in running text or labels: sans |
| **Hide a control only if it can never become active here** | A dead-looking live control costs attention | less noise | hiding a control that becomes active makes things appear and jump | paired controls whose state changes (Zurück/Weiter) stay visible, disabled. Progressive disclosure is powerful when what it hides is opened on purpose |
| **Controls own their state** | State far from its control forces the user to link them in their head | one fact, one place; seeing = changing | controls vary in width with their value | result count and range belong to the pager; sort direction to the column head |
| **Nothing loud outranks the page's main content** | Weight claims importance; the eye lands on the loudest thing first | first glance lands on the job | chrome less discoverable for first visitors | where the control is the content (start-page search) |
| **At most three primary filters in the heading sentence** | The sentence stays one readable line; common dimensions get the fast path | short heading, one click for the common case | a second, traditional mechanism for the rest; "primary" needs a real basis | swap a dimension in when usage says so; three stay three |
| **Inherit first; a part sets only what differs** (owner, 2026-09-27) | Colour, font, line-height and letter-spacing flow from the context; a part that restates them breaks when the context changes (a hint, a band, dark mode) | fewer declarations, parts that fit wherever they are placed | form controls do not inherit by browser default: the elements layer resets them once (`font`, `color`, `letter-spacing: inherit`) | a part may set a value only when it differs from its parent on purpose (a quieter hint, an error colour, a hover change); a marker or icon inside text never sets its own colour or size. Review: delete any declaration equal to the inherited value |

### Live-review rulings (owner, 2026-09-26)

- **No role labels.** Nothing says "nur Archivare"; the role shows in what the page offers.
- **No redundant marks.** A list titled "Meine Entwürfe" does not mark each item "Entwurf".
- **No off-topic actions.** A resume list carries no create action ("Neu erfassen").
- **Drafts on start = one quiet line** under the search: "Weiter bearbeiten: <Titel> · <Titel>".
- **The archive heading is the search sentence** (live pick, 2026-09-27): "Suche [field] in
  Gruppen des DPB · alle Jahrzehnte · jeder Typ  + Filter". One face, one size; the field is the
  one real input (the page's primary action). Set filters ink, open ones quieter; centre dots
  separate them; no chevrons, no trailing × (removal = "alle …" in the slot's menu). Heading and
  filter are one fact, so one element. No kicker, no chip row, no header search on this page.
  S: the field takes its own line, one primary filter stays, the rest fold behind "Filter".
- **Column heads** in sans, title case — no mono capitals anywhere as a label voice.

## 1b. Navigation architecture (owner, 2026-09-27)

Destinations are few: **start · one list · article · forms (edit, new, bulk) · door.**

| Rule | Intention | Gain | Cost | Boundary |
| --- | --- | --- | --- | --- |
| **Targets are presets of the one list** (Bestand, decade, type, search, Zuletzt, Meine Entwürfe, Unsortiert, later Papierkorb / Eingangskiste) | what people pick is a scope, not a place; one list page serves every scope | one pattern to learn; every preset is a URL; new "targets" cost no new screen | every preset must be expressible in the search sentence (Meine Entwürfe needs secondary filters; sort-only presets like Zuletzt need a visible sort) | curated content with its own text is not a preset |
| **The start page is a composition of presets** | it only decides which preset families deserve a compartment | simple page; cost/gain per compartment | the start page carries all "browse" discovery | — |
| **Top bar: wordmark · "+ Neu …" (archivists) · Abmelden** | wordmark = home; one create entry findable from anywhere; logout on shared machines | nothing to decode for members | no visible "browse" item — the start page must guide | no account name (users know who they are); no "Archiv"/"Bestände" items (not destinations); no Werkstatt (a new screen for jobs that have a place in context) |
| **Breadcrumbs show the place, not the path** | where the article lives in the archive; each step opens the scoped list | orientation + a way onward | — | none on start (root) or list (the sentence is the location). The way back to a search is browser Back (URL keeps the state), no second back link |

Start-page compartments: search · Bestände · Zeitleiste (L) · **by type** (new) · Zuletzt hinzugefügt
(hidden while all dates are the import date) · "Weiter bearbeiten" (archivists) · later Highlights =
curated pinned articles (not now).

Open: compact header search on article pages.

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
