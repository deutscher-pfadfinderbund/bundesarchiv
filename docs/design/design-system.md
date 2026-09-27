# Bundesarchiv design system

Status: LIVE DOCUMENT (owner, 2026-07-10) — updated as design decisions land;
no formal acceptance step. Governs all web UI from Part 4 on.

**The monochrome system "Druckschwarz" (owner, 2026-09-27)** replaces the violet
"stamp ink on paper" look. Its visual digest is `DESIGN.md` at the repo root; its
proof is the mock system in `docs/design/explorations/2026-09-26-monochrome/system/`
(`system.css`, `gallery.html`, `icons.svg`, `autocomplete.js`) and the archivist
screens built on it (`a1-formular/`, `a2-sammel/`, `a3-artikel/`). Since the retoken wave
(Wave T, 2026-09-27) the app's `tokens.css` is the normative token source; components still
carrying the old structure are measured against this document and change in their own wave.

**Enforceable half:** `design-review-law.md` (same directory) — the review
catechism, the cue register (the ONLY licensed visual cues, MAY-only), the
cascade rules, and the lintable subset. Owner-ratified 2026-08-06; reviews
and the design gate run against it.

## Construction law (owner, 2026-08-05)

How UI gets BUILT — these rank with the visual laws below. Background: agents
tend to fill gaps with invented chrome and ad-hoc markup; these rules make
simplicity checkable instead of a matter of taste.

- **Semantic HTML (2026) is the basis.** Native elements and their built-in
  behavior first (`form`, `fieldset`, `dialog`, `details`, `nav`, `table`,
  `output`, …); a div-plus-CSS reconstruction of something HTML already
  provides is a defect. Deviate from browser-plain only where a law here or
  the spec demands it.
- **Composition model, three layers** (owner, 2026-08-06; replaces the
  earlier atoms→molecules→layouts→pages ladder):
  1. **Components** — owned components (owner, 2026-09-25 —
     `owner-interview-2026-08.md`, "Component architecture rulings"). The
     outer element carries one class named for the component; its one CSS
     section, in the existing layer file and named like its template, styles
     only below that class. Its knobs — custom properties with a
     component-scoped name and a fallback, listed at the top of its section —
     are its API: compositions set knobs and place it, never select inside it.
     Facts about one field (width, Signatur ink) come from the field registry
     as markup, never from CSS keyed on an input's `name`. Semantic HTML
     first. Reuse-first: no ad-hoc one-off markup where a component exists,
     no redundant near-duplicates; anything genuinely new is added
     DELIBERATELY — named, filed, entered in the component inventory
     ("Component mapping") — or it doesn't ship.
  2. **Views** — self-contained work surfaces (facet panel, result ledger,
     article reader, edit form, confirm panel). Viewport-agnostic: a view
     adapts to its CONTAINER (`@container`), never to the screen. One
     implementation per view — the reader in the workbench pane and on the
     detail page is the SAME view, composed differently.
  3. **Compositions** — arrangements of views per available space, built
     from a small set of reusable CSS layout primitives (Every Layout
     style: Sidebar, Stack, Cover, …). Desktop composes several views;
     narrow shows one at a time with navigation between them.

  **Precedent rule:** a new view copies the nearest approved view and
  changes the minimum. Deviating from precedent needs an owner ruling —
  the approved views are the framework; there is no separate screen spec.

  References: Every Layout (Pickering/Bell — composition primitives),
  CSS container queries (view adaptivity; inside the browser floor),
  Atomic Design (Frost — terminology: view ≈ organism).
- **Provenance.** Every visible element traces to a named archivist wish
  (`docs/requirements/`), an owner ruling, or a spec section
  (`docs/design/part-4-web.md`). No element exists "for completeness."
- **Consistency beats novelty.** The same action looks and behaves the same
  everywhere; one pattern per problem. A second variant of an existing
  pattern needs an owner ruling, not an agent's judgment call.
- **CSS: the cascade, not a class taxonomy** (owner, 2026-08-05; Tailwind
  considered and rejected — no Node build step, and utility soup fights the
  semantic-HTML basis). Style semantic elements in scoped contexts using
  modern native CSS (nesting, `@scope`, `@layer`, `:where()` for
  low-specificity defaults); consistency comes from the custom-property
  tokens (the three layers above), which stay the single source of visual
  truth. Classes only where semantics cannot discriminate or on a component
  root (law C1), named for meaning. The legacy `c-*`/`l-*` prefix taxonomy
  is DEPRECATED — do not extend it; it dissolves in one deliberate rework
  wave (no piecemeal migration: two coexisting class systems is the worst
  state).
- **UI waves end at the design gate, judged on pixels.** Deliverable is
  before/after gallery renders (`docs/agents/design-gate-brief.md`) for the
  owner's verdict — agent prose about the UI is not acceptance. Subtraction-
  first: prefer waves that only remove.

## Rework-wave charter (owner interview, 2026-08-06)

The one deliberate wave that dissolves the `c-*`/`l-*` taxonomy. Scope
rulings (binding; source: `docs/requirements/owner-interview-2026-08.md`):

1. **Markup may change.** Where a native element replaces a div
   construction, replace it in the same wave (`<dl>` for the Akte
   key/value rows, `<fieldset>`, `<search>`, `<nav>`, …) — the cascade
   must style real semantics, not re-labelled divs. Classes survive only
   where semantics cannot discriminate, named for meaning. The target
   structure is the three-layer composition model above: the taxonomy
   dissolves into components + views + composition primitives, and the
   pane/detail-page duality becomes one reader view in two compositions.
2. **Delete `components-papier.css`** and the components-demo variant
   toggle. One look; the papier experiment is over.
3. **Dissolve bare-element wrapper components** (`button.html`,
   `input.html`, `select.html`) into plain semantic HTML styled by the
   cascade. Structural atoms stay (signatur_tab, facet_group, ledger_row,
   pagination, …).
4. **Demo pages are the storyboard.** `components_demo` / `layouts_demo`
   stay, and every component change updates them in the same wave —
   lockstep is the price of keeping them.
5. **Fold vs column-drop at the gate.** SETTLED (owner verdict 2026-08-07,
   on pixels): column-drop won over the fold as THE width behavior; the
   two-line fold survives only under the phone-width ~32rem container
   query (kept below the narrowest pane-open container) as the last
   resort. The `?fold` switch, the pane-open fold and the losing CSS are
   gone; row anatomy never changes with pane state. *Addendum (owner,
   2026-08-07 round 2 — law C11 "intrinsic first"):* the drop steps
   themselves died the same day — their 60/52rem thresholds were invented
   and hid columns with space to spare (learning G.23). The width behavior
   is now INTRINSIC: mono columns sit at max-content, the Titel absorbs
   slack and ellipsizes first, every column stays visible above the fold;
   the ~32rem fold threshold carries its C9 content arithmetic.
6. **Tests move in the same wave, and e2e is mandatory.** Some unit/e2e
   selectors grip `c-*`/`l-*` names (`c-badge--entwurf`,
   `c-artikel-aktionen`, `l-zurueck`, …) — migrate them with the markup.
   A cascade rework is exactly the known regression class in `CLAUDE.md`
   (position/overlay rules on `hidden`-gated elements intercepting
   clicks), so the wave's gate is the e2e journeys, not gallery renders
   alone. An axe-core pass over the journey pages rides along (carried
   from issue #9) — the semantic-HTML upgrade is the moment to measure
   and fix the a11y crop.

Success criterion: net-negative diff in CSS lines and unique class names
(169 classes / ~2,344 CSS lines at charter time), zero visual regressions
outside the deliberately changed states, gallery renders as the verdict
medium.

## Method (every screen, every element)

1. Write the screen's job first: who, what they try to achieve, what success looks like
   (`explorations/2026-09-26-monochrome/SCREEN-JOBS.md`).
2. Price every element: cost (attention, size, reading) against gain for those users. High cost
   and low gain: cut. Visual weight follows gain, never build order.
3. Price again per size (S / M / L, below). An element worth its space on a desktop can be too
   expensive on a phone.
4. Price the fix too. A fix is a new element or a new signal with its own cost. If the fix costs
   more than the problem, keep the problem.
5. Every rule states intention, gain, cost and boundary. A rule without its reason gets applied
   where it hurts.

## Principles (owner, 2026-09-26/27)

| Rule | Intention | Gain | Cost | Boundary |
| --- | --- | --- | --- | --- |
| **Alignment gives structure** | With good spacing and alignment, content forms natural lines; the eye follows them without effort | simple on the eye, few objects | needs one strict grid and spacing scale | where no natural line appears, draw one (next rows) |
| **A line connects or anchors** | Ties two ends of a row so the eye does not slip across a long gap | eye stays on the row | each line is an object; many add up to noise | not above the first / below the last row, not under headers or filter bars — there the edge is spacing |
| **Frames highlight or create cohesion** | Where elements have no natural line between them, a frame gives them something that connects them | the group reads as one | a frame is the loudest line; frames where alignment already groups are noise | an input's edge, a chip, a floating panel; not for grouping things that already stand together |
| **One lead per row; facts one tier quieter** | Rows are scanned for the title; facts are read once a title catches | calm, fast scanning | none that matters | no step-up for the sorted column (next row) |
| **Don't signal what the user already knows** | A change in appearance says "something important happened"; the user who sorted already knows | no noise from the user's own action | — | the sort arrow on the active column is enough feedback |
| **Mono only for data in columns** | Fixed-width digits align, rows of values scan | a typeface with one meaning | fewer tools for labels | values in running text or labels: sans |
| **Hide a control only if it can never become active here** | A dead-looking live control costs attention | less noise | hiding a control that becomes active makes things appear and jump | paired controls whose state changes (Zurück / Weiter, the end arrows) stay visible, disabled |
| **Controls own their state** | State far from its control forces the user to link them in their head | one fact, one place; seeing = changing | controls vary in width with their value | result range in the pager; sort direction in the column head; audience in "Sichtbar für" |
| **Nothing loud outranks the page's main content** | Weight claims importance; the eye lands on the loudest thing first | first glance lands on the job | chrome less discoverable for first visitors | where the control is the content (start-page search) |
| **At most three primary filters in the heading sentence** | The sentence stays one readable line; common dimensions get the fast path | short heading, one click for the common case | a second mechanism for the rest ("Filter") | swap a dimension in when usage says so; three stay three |
| **Inherit first; a part sets only what differs** | Colour, font, line-height and letter-spacing flow from the context; a part that restates them breaks when the context changes | fewer declarations, parts that fit wherever they are placed | form controls do not inherit by browser default: the elements layer resets them once | a part sets a value only when it differs on purpose (a quieter hint, an error colour, a hover change); a marker or icon inside text never sets its own colour or size. Review: delete any declaration equal to the inherited value. Not restating: binding a part to a role (`color: var(--ink)`) where a context may re-point it — `inherit` passes the resolved colour, not the role |
| **Red acts** | Red is the one colour; it must keep one meaning | errors and removals are found at a glance | — | field errors, edit conflicts, a removing control on hover / press / focus, the committing delete button; never for warnings or emphasis |
| **Mark the minority** | A marker on every field is no marker | the few special fields stand out | one legend-free convention to learn | "*" after required labels (in the label's ink); the note "intern" after archivist-only fields or sections |

Standing rulings (owner, 2026-09-26/27):

- **No role labels.** Nothing says "nur Archivare"; the role shows in what the page offers.
- **No redundant marks.** A list titled "Meine Entwürfe" does not mark each item "Entwurf".
- **No off-topic actions.** A resume list carries no create action.
- **No mono capitals** as a label voice anywhere; column heads in sans, title case.
- **No dashes as separators**; centre dots separate.
- **Every signal carries information, exactly once** (owner, 2026-07-10): no labels restating the
  visible, no badges for default states, no filler chrome.
- **Archivist ergonomics rank with the visual laws** (owner, 2026-07-11). A weekly work tool:
  tab order = field order, Enter submits the primary action and never publishes, autofocus lands
  where the work starts, serial workflows (Duplizieren, bulk edit) get the fewest round-trips.
- **Modes follow the OS.** `color-scheme: light dark` + `light-dark()` per role; no toggle in v1.
  Dark is tuned, not inverted.
- **Modern CSS floor** (owner, 2026-07-09): ~2024+ evergreen browsers (`light-dark()`, `:has()`,
  popover, `lh`); progressive enhancements (`field-sizing`, anchor positioning) degrade to a
  working default.
- **Pfadfinder details are extensions, not structure** (owner, 2026-07-09).

## Navigation architecture (owner, 2026-09-27)

Destinations are few: **start · one list · article · forms (edit, new, bulk) · door.**

| Rule | Intention | Gain | Cost | Boundary |
| --- | --- | --- | --- | --- |
| **Targets are presets of the one list** (Bestand, decade, type, search, Zuletzt hinzugefügt, Meine Entwürfe, Unsortiert) | what people pick is a scope, not a place | one pattern to learn; every preset is a URL; new "targets" cost no new screen | every preset must be expressible in the search sentence | curated content with its own text is not a preset |
| **The start page is a composition of presets** | it decides which preset families get a compartment | simple page; cost / gain per compartment | the start page carries all browse discovery | — |
| **Top bar: wordmark · "+ Neu …" (archivists) · Abmelden** | wordmark = home; one create entry from anywhere; logout on shared machines | nothing to decode | no visible browse item — the start page must guide | no account name, no browse items |
| **Breadcrumbs show the place, not the path** | where the article lives; each step opens the scoped list | orientation and a way onward | — | first step "Archiv"; none on start or list (the sentence is the location); the way back to a search is browser Back |

- The list's heading is the search sentence: "Suche [Feld] in Gruppen des DPB · alle Jahrzehnte ·
  jeder Typ + Filter". Set filters ink, open ones quieter, centre dots between them; no chevrons,
  no chip row. S: the field takes its own line, one filter stays, the rest fold behind "Filter".
- Start compartments: search · "Weiter bearbeiten" (archivists, one quiet line) · Bestände ·
  Nach Art · Zeitleiste (L) · Zuletzt hinzugefügt · later Highlights. Phone start: search and
  "Weiter bearbeiten" only.
- Article page: media left, facts right when a square preview exists (a PDF or scan gets its first
  page rendered as preview); otherwise one column, no placeholder frame.
- Edit form: sections Kerndaten → Beschreibung → Einordnung → Herkunft → Medien → Weitere
  Angaben, all open; the title field is the page heading; state and audience ("Status", "Sichtbar
  für") live in the form's margin next to Speichern.

## Space budget — three sizes

Sizes are container widths: **S** < 40rem (phone), **M** 40–80rem, **L** ≥ 80rem. Every component
declares per size one of: **full**, **compact** (same job, less space), **folded** (behind one
disclosure opened on purpose), **absent**. Archivists work mostly on L; members and link-holders
mostly on S. L is tuned for archivist work (side columns, the sticky form margin, bulk actions);
S for finding and viewing (one column, one primary task on the first screen, filters folded, no
charts, no placeholder areas). Type follows the viewport, not the container, so a heading keeps
its rank in a narrow column. A page-level arrangement whose content box never reaches 80rem asks
the viewport (`@media`), not a container.

## Tokens

Components consume **roles**, never values; a hex in component CSS is a defect. Roles are
re-pointed by a surface (the top bar) for its subtree; a floating panel points them back to the
page. Values: `DESIGN.md` frontmatter (light) and `.impeccable/design.json` (the light-dark pairs).

| Role | Job | Contrast floor |
| --- | --- | --- |
| `--ground` | page and floating panels | — |
| `--ink` | content text, primary fill, focus ring | 4.5:1 on ground |
| `--ink-2` | secondary text only | 4.5:1 (7:1 light) |
| `--ink-3` | the note ("intern") | 4.5:1 |
| `--rule` | the connecting hairline, two-ended rows only | none (decorative on purpose) |
| `--edge` | control, chip and panel edges | 3:1 (non-text) |
| `--faint` | disabled controls, placeholder drawings | exempt (inactive), tuned visible in dark |
| `--band-*` | the top bar's inverse band | 4.5:1 within the band |
| `--error` | errors, conflicts, removing controls about to act | 4.5:1 on ground |

- **Type roles:** wordmark, title, heading, subhead, entry, query, body, control, meta, label,
  note, data. Every text node maps to exactly one role; an ad-hoc size or weight is the
  typographic raw hex. Families: system serif (wordmark, section headings, article titles),
  system sans (everything else), system mono (data in columns).
- **Space:** the 4px scale `--space-1` … `--space-10`, with roles `--gap-section`, `--gap-block`,
  `--gap-head`, `--gap-page`, `--pad-row`, `--gutter`. A section gap beats every inner gap by far.
- **Lines and sizes:** `--line-width` 1px, `--focus-width` 3px, measures (`--measure`,
  `--measure-prose` 65ch, `--measure-title` 30ch, field and column measures).
- **Shape:** square corners everywhere; no radius, no bevel, no shadow. `--placeholder` is the one
  drawing for an item without an image.
- **Icons:** one stroke set (24px grid, stroke 2, `currentColor`): `components/icon.html` in the
  app, `system/icons.svg` in the mock, name for name.

## Component mapping

The mock system's components (proven in `system/gallery.html`; the a1/a2/a3 folders' own CSS holds
proposals still waiting for a ruling): topbar, search-field, search-sentence, section-head,
register, ledger, pager, facts, media, crumbs, resume, menu (native popover), button, mark,
note, icon, autocomplete (single, and multiple with chips), title-field. Form parts proven in
`a1-formular/`: field (with the "*" and "intern" markers), record margin (status, Sichtbar für,
conflict notice, version line), file-row, upload ("+ Dateien hinzufügen"), help (ⓘ + popover),
remove (the one ×), add ("+ …"), pairs.

### Component inventory

The app's owned components today (law C1). The retoken and component waves convert them to the
monochrome system; each row changes when its component does.

Every owned component (law C1), its root and its one CSS section. The design lint reads the Root
column: a compositions-layer selector may reach a root and never past it. A new component joins
this table. Views (`_results`, `_header`) and layout primitives (`.frame`, `.column`, `.split`,
`.form-sheet`, `.field-grid`) are compositions, not components. `_filterset` and `_trefferzahl`
are parts of the filter rail; they are split out only as swap units (law C7).

| Component | Root | Template | CSS section |
|---|---|---|---|
| Action row | `.actions` | inline | `components.css` action rows |
| Toolbar | `[role="toolbar"]` | inline | `components.css` action rows |
| Badge | `.badge` | `components/badge_visibility` | `components.css` badge |
| Note | `.note` | inline (`_feld`, the edit form's Weitere Angaben) | `components.css` note |
| Help | `.help` | inline (`_feld`) | `components.css` help |
| Title field | `.title-field` | inline (edit form) | `components.css` title-field |
| Crumbs | `.crumbs` | inline (edit form) | `components.css` crumbs |
| Section head | `.section-head` | inline (edit form) | `components.css` section-head |
| Record margin | `.record-meta` | inline (edit form) | `components.css` record-meta |
| Remove | `.remove` | inline (edit form: media rows, Weitere Angaben) | `components.css` remove |
| Add | `.add` | inline (edit form: Weitere Angaben, upload) | `components.css` add |
| Upload | `.upload` | inline (edit form) | `components.css` upload |
| Popover | `.popover` | inline (`_feld`), `workbench/_hilfe_datierung` | `components.css` popover |
| Mark | `.mark` | `components/mark_lifecycle`, inline (dirty register, Titelbild) | `components.css` mark |
| Signatur mark | `.c-sig` | `components/signatur_tab` | `components.css` Signatur mark |
| Facet group | `.facet` | `components/facet_group` | `components.css` facet group |
| Menu | `.menu` | inline (`_header` and the edit form's margin, both popovers) | `components.css` menu |
| Filter chip | `.chip` | inline (`_filterset`) | `components.css` filter chip |
| Ledger | `.ledger` | `components/ledger`, `ledger_row` | `components.css` ledger |
| Pagination | `.pager` | `components/pagination` | `components.css` pagination |
| Empty state | `.empty-state` | `components/empty_state` | `components.css` empty state |
| Icon | `.icon` | `components/icon` | none |
| Field | `.field` | `workbench/_feld` + standalone forms | `components.css` field |
| Media register | `.media` | inline (edit form) | `forms.css` media register |
| Panel | `.panel` | inline (confirm pages, CAS conflict) | `forms.css` panel |
| Field diff | `.diff` | inline (CAS conflict) | `forms.css` panel |
| Feld chooser | `.chooser` | `workbench/_feldwahl` | `layouts.css` Feld chooser |
| Sammelbearbeitung | `.bulk` | `workbench/_sammelleiste` | `layouts.css` Sammelbearbeitung |
| Filter rail | `.filterrail` | `workbench/_filterrail` | `layouts.css` filter rail |
| Pane | `.pane` | `workbench/_pane` | `layouts.css` preview pane |
| Failure banner | `.error-banner` | inline (`base`) | `layouts.css` failure banner |
| Cover Platte | `.platte` | inline (`detail`) | `detail.css` cover Platte |
| Record card | `.facts` | inline (`detail`) | `detail.css` record card |
| Plate register | `.filmstrip` | inline (`detail`) | `detail.css` plate register |

### Roles

| Element | Treatment |
|---|---|
| Page and floating panels | `--ground`; panels add a 1px `--edge`, no shadow |
| Top bar | the inverse band (`--band-*`); menus opened from it are page surface |
| Primary action | solid `--ink`, `--ground` text; hover inverts to outline |
| Add action ("+ …") | text in meta type, no frame; underline on hover |
| Field | label in label type, `--ink-2`; control edge `--edge`; hover edge `--ink`; focus ring; error / conflict: doubled `--error` edge |
| Required / archivist-only | "*" in the label's ink / the note "intern" (`--ink-3`, note type) touching the label or heading |
| Lifecycle | "Entwurf" as a mark (words, `--ink-2`), never a box; published renders nothing |
| Removal | the one ×: `--ink-2`, `--error` on hover / press / focus; `hx-confirm` where it deletes for good |
| Disabled | `--faint`, still visible, not interactive |
| Focus | 3px `--ink` outline, 3px offset; where an underline is the field, the underline thickens instead |

## Named voice patterns (extracted 2026-08-28)

Composition precedents the critique round confirmed as this product's voice.
Not cues (nothing here needs a register row) — precedent-rule targets: a new
surface with the same job copies these, not a fresh invention.

- **Consequence disclosure** (`sammelbearbeitung_pruefen.html`, the orphan
  branch): a side effect is enumerated at the record level — one quiet row
  per affected record, `{alt} → {neu}` (or `→ (leer)`), weight emphasis, no
  loud color — and the committing button relabels itself to name the full
  consequence ("Medienart setzen, Dokumenttyp leeren"). Any surface that
  destroys or overwrites data per-record renders this grammar; a bare count
  is not a disclosure. (The bulk-overwrite P0 wave extends this to the main
  apply path.)
- **A bulk outcome is not an error** (`sammelbearbeitung_ergebnis.html`): a CAS
  race or stale-selection outcome in the bulk result renders as quiet register rows — no red,
  no alert tone — each row carrying its own onward action ("Diesen Artikel
  bearbeiten"), plus one collective recovery ("Diese N erneut auswählen").
- **An edit conflict is shown as invalid** (owner, 2026-09-27; supersedes the earlier
  "conflict is not an error" for the edit form): the conflicting fields carry
  `aria-invalid="true"` and the doubled red edge, with "Inzwischen gespeichert: …" under each;
  the margin opens with the notice (3px red rule, red subhead, one sentence whose field names
  are links). Not the `:invalid` pseudo-class: `setCustomValidity` would block the save that
  resolves the conflict.

## Contrast

The floors in the Tokens table are the contract, judged at the design gate on renders of every
state in both modes. Colours are chosen once in the token layer and change nowhere else.

## Extensions (optional, non-integral)

Each is additive, isolated behind its own class names, removable without
touching the system: Waldläuferzeichen as state language (empty results, 404,
"noch nicht eingeordnet"); Kohte silhouette in the empty state; pennant/trail
geometry for micro-icons (chip ✕, markers). Implement opportunistically,
never at the cost of the core.

## Order of work (owner, 2026-09-26/27)

1. The rules into the law — this document, `DESIGN.md`, and the cue register of
   `design-review-law.md`. Done 2026-09-27.
2. Monochrome retoken of `tokens.css` + the top bar, with the design lint on the new register.
   Done 2026-09-27 (Wave T). The door page follows as its own wave (auth surface).
3. Components per the system, one writer each (Wave C's owned-component model), each rendered in
   the component gallery at S / M / L before a page uses it.
4. Pages: start, list, article; each checked against its screen-job table.
5. The edit-form recompose (`WAVE-R.local.md`), on the a1 mocks.
