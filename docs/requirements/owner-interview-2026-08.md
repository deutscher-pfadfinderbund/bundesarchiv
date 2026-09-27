# Owner interview 2026-08 — ratified requirements and audit consequences

Source: project-review interview with the owner (2026-08-05), conducted to
separate real requirements from accumulated assumptions. Statements below are
the owner's rulings; each section ends with the concrete consequences for the
codebase. This document is binding input in the same way as
`archivist-wishes-2025.md`.

## Rollout plan (definitive)

1. **Deployment 1** — no content: preview of the UI and capabilities for the
   archivists. **Editing (cataloging form, bulk edit) is part of this
   preview.** Search may be rudimentary; the full FTS/facet feature set is
   not preview-blocking.
2. **Deployment 2** — ingestion of the existing data (real data, not
   samples: "archivists will judge the system on their own data").
3. **Switchover** old → new system once the archivists are happy.

The preview exists so archivists "check out the system and tell me early if
they need anything else" — feedback loop first, completeness second.

## Storage

- **Target state:** Nextcloud (a Hetzner StorageShare, WebDAV) is the canonical
  long-term store. The archive server hosts only ephemeral data (search
  index, thumbnails). Everything important lives in media files and Markdown.
- **v1:** filesystem backend only. Graduation to WebDAV comes later; the
  modular persistence layer exists exactly so this switch is possible.
  Multi-tiered persistence (local read cache in front of WebDAV) is
  acknowledged as complicated and **deferred** — a target-state idea, not a
  requirement now.
- **Sole-writer holds for v1.** Humans read the store (mirror) but do not
  write it; "humans edit files in Nextcloud" is a future nice-to-have.
- **Nextcloud inbox directory (near-term):** a directory humans drop batch
  uploads into, which the app ingests. Distinct from the member-facing
  Digitale Eingangskiste web form (`archivist-wishes-2025.md`), which stays
  a future feature. Design constraint: the inbox must live **outside the
  reconciled roots** (or get an explicit carve-out), otherwise the
  reconcile delete pass would treat human drops as orphans.

Consequences:
- Keep backend modularity; do not build the cache layer now.
- Spec the inbox directory when it is scheduled; note the reconcile carve-out.
- The interim filesystem-only stage is the one window where the VPS holds
  the canonical data — it needs an explicit (simple) backup story until the
  WebDAV graduation.
  (Superseded 2026-09-19 — see the addendum: backup is out of scope.)

## Access model

Three access paths, no fourth:

1. **Members with Keycloak accounts** — their **Keycloak groups shall be
   used** for group-restricted material. Group truth lives in Keycloak.
2. **Members without accounts** arrive via **secret links** (capability
   URLs, no login prompt), including links that carry group identity. These
   are the "anonymous" users.
3. **Archivists always log in via Keycloak.**

Rulings:
- **No public browsing, ever.** "Public" means "anyone holding a link", not
  the open internet.
- Group visibility is **not needed for the first preview** but is required
  soon after.
- Per-item links (for referencing single articles in e.g. public posts) are
  a future feature.
- The domain ladder Public ⊃ Members ⊃ Groups (GROUPS narrows Members)
  matches the owner's model and stays.

Consequences:
- ADR 0018's **guest-password path becomes capability links**: the link's
  token mints the Viewer cookie directly (revocation = revoke token) instead
  of a shared password prompt. Amend the ADR.
- Promote Keycloak group mapping from "unused for now" (ADR 0018) to
  **required soon** — today OIDC members get `groups=()` and could never see
  GROUPS-tier articles.
- Rename/redefine the `PUBLIC` tier so the code says "link-accessible", not
  "anonymous internet".

## Byte-identical-404 law: relaxed

Owner: "This can be relaxed. We aren't Fort Knox." A plain access-denied
page is acceptable; existence-hiding via byte-identical responses is not a
requirement.

Consequences:
- **Keep** (real leak prevention, inside the owner's testing razor):
  filtering unauthorized content out of search results, listings, and facet
  counts (`tests/index/test_leaks*.py` concept).
- **Drop**: the byte-identical response discipline (the byte-for-byte deny
  comparisons in the route × tier leak matrix and the per-route tests) and
  the anonymous-redirect byte-uniformity contract in ADR 0018. The matrix
  itself survives slimmed — its status assertions and exhaustiveness gate
  are leak prevention (see `tests/CLAUDE.md`). Supersede
  the relevant parts of ADR 0001/0012/0018 with a short amendment.

## Testing philosophy (standing directive)

Extensive testing only for behavior that is **domain-relevant** or where a
defect means **data loss or data leak**. Everything else gets ordinary,
proportionate coverage.

Named example of overkill: the "color math" namespace
(`tests/app/web/color_math.py` + `tests/app/web/test_design_tokens.py`,
~260 lines) for colors that are chosen once. Deletion candidate.

## Migration (blocks deployment 2, not deployment 1)

- The old system's pg dump is inspected; `docs/design/migration-feasibility.md`
  is verified against the real dump (2,485 rows in
  `tests/test_data/archive_items.txt`) and is treated as correct.
- Still needed from the old system: the `document_type` lookup table export,
  the django-filer tables, and the actual media binaries.

## Operations

- Runs on the Bund's VPS; the owner has full control, and others hold root
  access as a fallback.
- The Nextcloud is a hosted Hetzner StorageShare.
- Design intent confirmed: the archive server only hosts ephemeral data;
  **the files (media + Markdown) are the only thing that must never be
  lost** — the search index is disposable and rebuildable by design.

## Addendum (owner, 2026-08-05, post-audit)

- **Backup ruling:** the WebDAV store on the StorageShare is the primary backup
  solution — the file tree is deliberately simple precisely so a full backup
  is nothing more than downloading it as a zip. This resolves the open
  "interim backup story" consequence above: run the WebDAV mirror against the
  StorageShare from day one.
  (Superseded 2026-09-19 — see the addendum: backup is out of scope.)
- **No strict deadline** for the preview deployments.
- **Auth is the large blocker** for deployment 1 — ADR 0018 is designed but
  not built (only the dev viewer-switcher exists).
- **WhiteNoise (ADR 0016) is not merged and maybe not complete** — static
  files are still hand-served views.
- **UI ruling:** the owner is not yet happy with the UI — "agents always make
  it very complicated." Simplicity is a requirement, not a style preference:
  UI waves should remove complexity before adding capability.
- **UI construction ruling (2026-08-05):** modern (2026) semantic HTML as the
  basis; sensible components built up in a hierarchy (atoms → molecules →
  layouts → pages); no ad-hoc or redundant components; anything special is
  deliberate; consistency is paramount. Codified as "Construction law" in
  `docs/design/design-system.md`.
- **CSS methodology ruling (2026-08-05):** not fond of the `c-*`/`l-*`
  classes — either full Tailwind or proper use of the cascade; preference is
  modular and flexible, consistent through variables. Resolved to: modern
  cascade-based CSS over the existing custom-property tokens; the prefix
  taxonomy is deprecated, dissolved in one deliberate rework wave.

## UI-system interview (owner, 2026-08-06)

Round 2, scoping the CSS/markup rework wave. Rulings:

- **The wave may touch markup.** Semantic-HTML upgrades are in scope — a
  native element replacing a div construction is part of the same wave, so
  the cascade styles real semantics instead of re-labelled divs.
- **The papier variant is cut.** `components-papier.css` (~513 lines) is
  reachable only via the components-demo toggle, never by the live app; a
  second visual theme doubles every styling decision for nothing. Delete in
  the wave.
- **Bare-element wrapper components dissolve.** An include that renders one
  native element (`button.html`, `input.html`, `select.html`) is more
  complex than the tag; with the cascade styling elements directly these
  wrappers go. Atoms survive only when they bundle real structure
  (signatur_tab, facet_group, ledger_row, pagination, …).
- **Demo pages stay** — "it's like a storyboard." `components_demo` /
  `layouts_demo` are the living styleguide and MUST be updated in the same
  wave as any component change (lockstep, or they rot into stale docs).
- **Materiality ruling: paper material — "but not like the generic Google
  Material look".** The system reads as cut sheets on the gray desk, not as
  floating elevated surfaces: seed-tinted sheets, hairline edges, one 2px
  thickness cue; no shadow stacks, no ripple, no gradients-as-lighting, no
  textures. The papier variant FILE is still cut (one theme only); its
  recipe is promoted to the baseline (cue-register row 8,
  `docs/design/design-review-law.md`).
- **Bevel ruling:** single cut, leading (top-left) corner, drawer-tab family
  only (`.c-sig`, `.c-facet-tab`). Trapezoid (both top corners) is reserved
  for a possible future register-tab component for view navigation — not
  licensed until that component is approved.
- **Exploration verdicts (owner, 2026-08-07)** — directional endorsements
  from the five workbench explorations, to be executed as deliberate waves
  (register/token edits where noted), not ad hoc:
  - **05 Eisengallus:** the LINE-TABLE (bound-register) ledger style is
    liked; the Kapitälchen-serif "Bundesarchiv" wordmark is liked (a new
    display type role — owner-only tokens.css entry); ideas (a)–(c)
    endorsed in general. Hue itself NOT switched (see 01).
  - **04 Lesesaal:** the simpler member browsing mode is good; the serif
    pane/reader title is liked (reading type role). Open question the
    composition must answer: how readers FILTER in this mode.
  - **01 Flaschengrün:** no seed change now — recorded as proof the swap
    stays a one-line decision.
  - **02 Filterleiste:** facets in a top filter bar are a CANDIDATE FOR THE
    PRIMARY filter interaction; the sidebar possibly only on large screens.
  - **03 Karteikasten:** card results liked as an ALTERNATIVE, user-chosen
    view (harder to scan, but can show previews) — a view preference, not
    the default.
  - **Result-view switching (owner, 2026-08-07):** Lesesaal, table and
    cards are VIEWS the user switches between; the table (line-table
    ledger) is THE DEFAULT for now.
  - **Destructive actions may be red** (register row 5 amended: the one
    `button.danger` on a confirm surface).
  - **Title affordance:** clickability shows ON HOVER (link ink +
    underline) — no persistent link styling in the ledger.
  - **Header buttons** ("Suchen", "+ Neuer Artikel"): acknowledged not
    great, explicitly MINOR — no rework mandate yet.
  - **Bulk selection mark (owner, 2026-08-07):** NO inversion bar — the
    checked checkbox IS the selection mark; unchecked checkboxes reveal on
    row hover/focus (the same gesture that reveals the row toolbar — one
    hover opens the row's whole action surface, doubling as the
    batch-operations entry). Register row 3 narrowed to the facet active
    row; row 10 licenses the quiet pane-row highlight.
  - **Screen priority (owner, 2026-08-07):** finish the WORKBENCH first as
    the exemplar, learn from it, then propagate the learnings to the other
    screens (edit form, detail reader) — the precedent rule in action.
- **Rail-wave verdicts (owner, 2026-08-07, on REAL renders):** wordmark
  larger; the header create buttons are "horrid" — rethink via mocks (no
  ruling yet); Signatur column left-aligned and narrower; the filter rail
  loses its background band (lighter, more air below the navbar); the
  Sammelbearbeitung affordance is hidden until rows are selected —
  REVERSES the #16 cold-start-visibility ruling (progressive: no-JS keeps
  it visible, JS hides at zero selection); dropdown panels get an overlay
  shadow (register row 12) — the flat-furniture reading of row 8 applies
  to RESTING surfaces, not transient overlays.
- **Report artifact discipline:** the artifact shows the CURRENT state and
  open decisions only — history lives in git; the design explorations stay
  in the artifact as an inspiration annex.
- **Rail-wave round 2 verdicts (owner, 2026-08-07):** header buttons →
  Mock B (ONE quiet "+ Neu …" disclosure replaces the two create buttons;
  the search button goes quiet too); row hover stays underline-only;
  a COMPACT chip hit size is allowed (new dimension token, C5); add an
  "Alle Filter entfernen" link at the END of the chip row. Rail stays
  workbench-only (unobjected default).
- **Communication language (owner, 2026-08-07):** all agent communication
  and report artifacts in ENGLISH; German remains the product UI language
  (writer-brief law unchanged). No mixed-language reports.
- **Post-review decisions (owner, 2026-08-07):**
  - **Rail dropdowns stay mutually exclusive** (native accordion, one open
    at a time) and an open one closes on a live search.
  - **Fallback panel placement accepted:** where anchor positioning is
    unavailable, rail panels drop from the rail's leading edge rather than
    from the clicked button. Contained + readable is enough; per-trigger
    anchoring stays an enhancement (appendix F), never load-bearing.
  - **Cascade rule C12 confirmed as law** (an overlay positions against its
    control row, not its trigger).
  - **SIGNATUR DOMAIN FACT (owner, 2026-08-07):** Signaturen carry **no
    spaces**, and **8 characters is the practical ceiling** ("they could get
    longer, but I don't expect them to"). The canonical demo corpus gets ONE
    Signatur at that ceiling — the 30-character space-bearing example used
    while diagnosing the overflow bug was excessive and is not
    representative. Layout guards may still stress beyond the ceiling
    (Titel is genuinely unbounded free text), but renders and design
    judgment run on realistic codes (learning G.6).
- **Form-wave rulings (owner, 2026-08-08 — answers to the eight decisions in
  `docs/design/form-wave-brief.md`):**
  1. **Composition E** (the ruled record card + the reader's sheet in the pane
     column), **with A's two-column behaviour inside the card**: the card's
     sections break into two columns — "no breakpoint guessing, use a grid".
  2. **Actions live in ONE sticky row at the top** of the edit screen (the
     record row). The bottom sticky footer band and the separate lifecycle band
     both die.
  3. **Every identity fact is a field.** The edit screen carries NO title
     header — Titel and Signatur are inputs, so a header repeating them is
     duplication (Q2).
  4. **Rarely-used sections stay folded, with their values in the summary**
     (folding may never hide data).
  5. **The exposure statement is permanently on screen; publishing is one
     click.** The separate over-exposure preview gate retires.
  6. **Media row actions become icons** — arrow-up and arrow-down join the ONE
     vendored icon set (register row 9); the three text links per row die.
  7. **Keep the NATIVE file input.** A German browser renders German strings;
     the label-triggered replacement is rejected.
  8. **Cascade rules C13 + C14 adopted as law** (zero-specificity defaults;
     a composition styles only what it placed).
- **The mail-client fold is under review.** The owner asked why the results
  table changes shape when a row opens the pane (the 2026-07-10 fold
  ruling). Candidate replacement: stable row anatomy, low-priority columns
  drop as the table narrows. Decide at the design gate on before/after
  renders — not settled here.

## Design rulings (owner, 2026-08-22 — workbench critique + shape session)

- **Standing frame:** "Don't treat the existing design as 'complete' — it's
  still in development and has flaws." Critiques and issues must not codify
  incumbent patterns as settled law; "make A match B" findings become design
  questions unless the pattern is owner-ratified and undisputed.
- **Lifecycle mark — the gray ENTWURF word:** "Let's only keep the grey
  Entwurf. It's good enough for now." Quiet mono-meta text in
  `--on-surface-variant`; no amber, no box, no badge chrome; one treatment
  for the ledger and every reader header (pane, detail, edit). Register
  row 4 (amber badge) superseded when the wave lands. **"For now" is a
  lukewarm acceptance — revisit candidate per learning G.20.** Parked idea
  recorded below (cursive face).
- **Pane contract — scent:** "It kind of depends on the content and the
  available space. But in general, it should show a preview. Details on
  its own page." The pulled sheet previews (identity, media scent, few key
  facts); the detail page reads. Composition may flex with content and
  container; the pane never grows into the full reader. Full brief:
  `docs/design/pane-lifecycle-brief.md`.
- **Sortable column heads:** quiet resting affordance licensed in
  principle; concrete treatment open, decide on mocks at the gate. The
  2026-08-07 quiet-default rulings (hover-revealed bulk checkboxes, row
  toolbars, self-hiding Sammelbearbeitung) explicitly stand — NOT reopened.
- **Naming (via DESIGN.md, same day):** Creative North Star "The
  Archivist's Desk"; the seed violet's descriptive name "Stamp-Ink Violet"
  (hue itself unchanged — the Flaschengrün one-line-swap record stands).
- **Parked idea (inspiration annex, not licensed):** "Maybe a
  cursive/handwritten font for Entwurf… not important right now." A
  handwritten face for the draft mark — would be a new type role + register
  decision if ever picked up.

## Strategic rulings (owner, 2026-08-22 — application-wide shape session)

- **Shared views:** "Archivists not only manage the content, they also
  browse and research, just like the other members. So their views should
  be the same or similar." There is NO separate member UI: one shared
  browse/read experience for every tier; archivist capabilities layer onto
  the same views (role-gated actions), and the Lesesaal/table/cards
  switching serves everyone. Catechism Q3 reads accordingly: archivist
  CHROME stays out of what members see, but the underlying views are one.
- **Media viewing, v1 scope:** "Designed essentials, but simple for now.
  Everything else can be done in a future release." Proper image viewing,
  native audio/video players, PDF hand-off — designed, nothing exotic;
  multi-page scan navigation / in-page PDF / waveform-class viewers are a
  future release.
- **Shape order:** entry surfaces (D3) first — rides the deployment-1 auth
  blocker; detail+media (D1) next; member arrival (D2) largely collapses
  into the shared-views ruling plus D1's reader.

## Entry-surface rulings (owner, 2026-08-22 — D3 interview)

- **The door (root, unauthenticated):** wordmark + ONE sentence of context
  + Anmelden. Plus a quiet path for members without accounts: "Maybe we
  need to add a link for members who have no account yet and are
  confused" → resolved: the link contacts the archivists (mailto/contact
  address; a human answers, no page to maintain).
- **Capability-link arrival: straight into content.** Cookie minted
  silently, the reader/collection opens immediately — the link IS the
  door. No interstitial, no welcome step.
- **Identity chrome: none.** The header shows no name, no tier, no login
  state — for any tier ("Nothing visible"). Archivist identity is implicit
  in the editing capabilities present on the page.
- **Dead/revoked capability link:** the denied page adds one quiet line on
  this path only — "Dieser Zugangslink ist nicht mehr gültig" + contact
  hint. Revealing that a link existed is acceptable (consistent with the
  relaxed byte-identical-404 ruling above).
- **Abmelden lives in the footer** — a quiet line at every page's end,
  present only when a session exists. No logout in the header.
- **Keycloak round-trip failure is unrecoverable** — "Nothing we can
  really do." No designed error surface; the plain error page suffices.

## Reader rulings (owner, 2026-08-22 — D1 interview)

- **Record first.** The reader sheet leads with the identity header
  (Signatur tab, Titel, Datierung, gray ENTWURF when draft), then media,
  then the Akte facts. One composition for every article type.
- **Image series = vertical roll.** All images full-width in ADR-0015
  order, captions beneath each — scroll to see everything, no
  lightbox/strip machinery.
- **Bearbeiten is the reader's ONLY archivist action.** "The workhorse for
  bulk edits by the archivists is the table" — Kopieren, Löschen and
  everything serial stay on the workbench; the reader offers the one jump
  into deliberate editing.
- **No audience fact on the reader** — exposure lives on the edit screen
  only; the reader carries no access chrome for any tier.

## Craft rulings (owner, 2026-08-22 — spacing/color/hierarchy round)

- **Footer carries Abmelden only.** One quiet line at page end, rendered
  only while a session exists; nothing else lives there.
- **Reading-measure token: yes.** One deliberate non-color token
  (~65–70ch class) for prose surfaces; sheet compositions consume it.
  Enters tokens.css with the wave that first needs it (reader/door).
- **Amber parks for Submission.** Once the gray-ENTWURF wave supersedes
  register row 4, `--draft`/`--on-draft` stay in tokens.css with a comment
  reserving them as the future Eingereicht/Submission lifecycle channel
  (post-v1) — not deleted, not licensed.

## Bestand rulings (owner, 2026-08-22 — D4 interview)

- **The real tree is SHALLOW**: a handful of top Bestände, ≤2–3 levels —
  the UI may show the whole tree at once; no drill-down machinery needed.
- **Browsing: facet only, for now.** "I'm not sure. Let's go with facet
  only for now" — the BESTAND rail dropdown is the tree's whole UI; no
  shelf page, no Bestand header on the filtered workbench. **Lukewarm
  (G.20): revisit candidate**, likely after real data lands (deployment 2)
  when the archivists' browsing habits are visible.
- **A Bestand may carry an optional description.** Data model + edit form
  now; a reader-facing display surface exists only when a Bestand gets a
  face (deferred with the browse-entry revisit). Empty = nothing renders.
- **"Bestand" is law.** The CONTEXT.md label *Sammlung* is superseded;
  the registry is corrected in the same turn.

## Filter & search rulings (owner, 2026-08-22 — D2/D5 interview)

- **Lesesaal is the third result view under the SAME rail** (with table
  and cards; table stays default). Exploration 04's open question ("how
  do readers filter in this mode") is CLOSED: the rail filters all views
  identically; no separate reading-mode filter system. The serif reading
  role stays reserved for the Lesesaal view's own wave.
- **Smart facet counts.** Each rail dropdown's counts are computed with
  its OWN filter excluded (standard faceted-search counting) — a dropdown
  shows what switching that filter would yield. This fixes the zero-hit
  dead end (pivot stays possible) and stabilizes rail geometry between
  queries (groups no longer appear/vanish with the result set).
- **Datierung range: now.** Von/bis year inputs join the rail as a
  dropdown (EDTF `date_earliest/latest` bounds already support it).
  Archive research is date-driven; this does not wait for preview
  feedback.

## Character rulings (owner, 2026-08-22 — "the design is pretty boring" round)

Diagnosis accepted: the system is under-expressed, not under-designed —
its character carriers are each used once or never. Chosen levers:

- **Real typefaces (OFL, vendored)** — the drop-in swap tokens.css always
  reserved: a characterful working sans + serif replace the system
  stacks; roles and layout untouched. Candidates decided at a mock gate
  on renders, never in prose.
- **Waldläuferzeichen layer** — build the sanctioned personality
  extension (empty states, 404, micro-icons in trail-sign language).
- **Lesesaal reading view** — build the third result view with the
  reserved serif reading role.
- **First boldness peak: the EMPTY/404 states** — the Waldläuferzeichen
  debut where nothing competes. (The door stays briefed but is not the
  first peak.)
- **Motion: passed for now** — desk-plane motion stays licensed law,
  unscheduled.
- Standing constraint reaffirmed by the round's framing: the workbench
  stays quiet; no new chroma, tints, or effects — character comes from
  the system's own reserved carriers.

## Edit-form & reader rulings (owner, 2026-08-22 — post-critique round)

- **Reader brief amended (all four):** the Beschreibung prose section
  joins the composition; onward paths (Bestand crumbs + Schlagwort links)
  survive; reader-size image derivatives ship BEFORE the media roll; the
  Umfang row drops (len(media) is not a physical extent).
- **Speichern stays on the form** — save is a heartbeat with a saved
  confirmation; leaving is an explicit act (Zurück/Öffnen). Supersedes
  the save-and-exit flow; the "view first, edit deliberately" law is
  about ENTERING edit mode, unchanged.
- **Kopieren copies fields only, never media** — ratified (was unstated;
  copy is a cataloging template, scans attach fresh).
- **Autofocus on plain edits: Titel** — the first-empty walk runs only on
  the create→edit continuation; rare folds stay shut on re-edits. The
  serial flow keeps `?fokus=signatur`.

- **Typefaces: keep the system stacks for now.** "I can't really see the
  difference." No OFL swap; the vendored-faces option stays the recorded
  later drop-in decision. Revisit candidate — the verdict was
  indifference, not endorsement (G.20 flavor).
- **Label role: MIXED CASE.** `text-transform: none`, tracking ~0.02em —
  the letterspaced-uppercase label voice retires across the system (rail
  summaries, column heads, field labels, badges' base treatment). The
  ENTWURF register mark was excluded from the mock and keeps its own
  ruling (gray word). Tokens change: `--label-tracking` value +
  consumers drop `text-transform: uppercase`.
- **Sortable-head resting mark: HOLLOW GLYPH.** Muted △ at rest on
  sortable heads; the real direction glyph keeps the active sort. New
  cue-register row required when the wave lands (same slot family as the
  active-sort glyph).

## Radical-exploration verdicts (owner, 2026-08-23 — three concept mocks)

Context: owner asked for a radical personality redesign of the workbench;
three MOCK concept directions were rendered (sources preserved in
`docs/design/explorations/2026-08-23-radical/`).

- **R1 "Registratur-Brutalismus" looks best** — typographic conviction on
  white paper, black ink, heavy letterhead rule, oversized folio; the
  DIRECTION is endorsed. **But its central thesis is rejected: "The
  signatures aren't as important as you make them. Members don't really
  care for them at all."** Domain fact recorded: Signatur relevance is
  archivist-side; on shared views its visual rank must not exceed a
  member's interest (catechism Q9 — rank by the primary user's frequency).
- **Beige/warm paper: rejected** — "beige looks AI again" (the earlier
  warm-manila mock). Neutrals stay hueless.
- **Guide-card dividers: rejected for the real table** — nice, but fragile
  under dynamic sort.
- **R2 "Nachtarchiv" and R3 "Stempel & Marginalie": not adopted** —
  inspiration annex only (the circular postmark, margin-notes idea, and
  the night-ramp dark identity remain available motifs).
- **Session closed by the owner** — no build authorized from this round.

## Closing rulings (owner, 2026-08-22 — board-clearing round)

- **Reader/entry inferences i1–i6 all stand** (see the briefs): native
  players in the roll, PDF file cards with browser hand-off, tap-to-
  original (no lightbox), one quiet Bearbeiten header button, desktop
  reader at reading measure, Bestand facet shows the shallow tree
  indented.
- **badge_visibility.html: DELETE** (catechism Q1 verdict on the exhibit;
  the demo page drops its entry in the same change).
- **Chips keep `--type-meta` — "values shouldn't shout."** Closes the #45
  exemption question in the chips' favor. AND: **"labels don't
  necessarily need to be Caps either"** — the label role's
  uppercase/letterspacing treatment itself is now an OPEN question,
  system-wide (facet headings, column heads, badges). Decide on renders
  (G.7/G.14): a mock round showing uppercase vs mixed-case labels across
  the rail, ledger head, and reader — not ruled in prose.

## Follow-up ruling (owner, 2026-08-28)

- **ENTWURF carve-out dropped.** When the label role's uppercase retires
  (mock-gate verdict 2026-08-22), the draft register mark loses its
  exception too: it renders "Entwurf", mixed case, like every other label.

## Edit-form critique (owner, 2026-08-29 — on the post-label-wave render)

Owner reviewed `edit-form.light.1440` and rejected the surface's composition:
"in general the interface lacks hierarchy and structure." Findings, verbatim
in substance:

- **Section headings carry no rank** — "Kerndaten" and "Einordnung" are the
  same size as the field labels beneath them.
- **Too many horizontal lines** — the ruled-field underlines plus section
  rules read as noise.
- **The exposure card (right) is overloaded** — "way too overloaded", and
  the F9 Signatur chip "looks out of place". Broader signal: **"I'm getting
  more and more tired of the Signature label, it's overused."** Extends the
  2026-08-23 domain fact (members don't care about Signaturen) toward
  archivist surfaces: presence budget, not just member-side rank. Cue
  register rows 1–2 stand until an explicit ruling; new surfaces spend
  Signatur marks sparingly.
- **Ragged field rhythm** — empty underline inputs with hints/echoes on
  their own rows read as "values on another row".
- **Field order unclear** — Kerndaten/Einordnung columns, then a collapsed
  Herkunft ("3x leer"), then Beschreibung, then collapsed Zugriff, then
  Medien, then a trailing collapsed Weitere Angaben: open/collapsed/open
  sandwich with no discernible logic.
- **Medien section spacing broken**; the native file input + "Hinzufügen"
  pairing is not understood as an affordance.
- **Trailing collapsed section feels wrong** as a page ending.
- **The record row confuses**: "Zurück zur Suche" beside the amber Entwurf
  badge, with the search bar directly above. (The amber box already dies
  with the ruled gray-ENTWURF wave.)

Consequence: the edit form needs a RECOMPOSE wave (shape first, mocks at a
gate), not patches. The endorsed R1 Registratur-Brutalismus direction
(typographic conviction, heavy letterhead rule) is the raw material for the
hierarchy answer.

## Edit-form mock-gate verdicts + Signatur ruling (owner, 2026-08-29)

On the recompose mocks (`docs/design/explorations/2026-08-29-editform/`):

- **E1 "Registerbogen" + E2 "Erfassungsbogen": endorsed** — "nice in
  general". The build direction is their hybrid.
- **E3 "Ein Blatt": rejected** — "too loose".
- **E2's full-width Medien band: rejected** — "breaks the layout without
  any real reason". BUT: "making use of the horizontal space on larger
  screens is good" — the two-column density itself is endorsed.
- **Title duplication flagged** (open question for the build): "Lagerchronik"
  as page heading AND as the Titel field "maybe confusing".
- **Scope law for the recompose:** "Only focus on general extractable
  layouts and components. Specific details about article fields might
  change anytime." The article's field set is deliberately dynamic (custom
  fields, ADR 0009) — the composition must be field-agnostic: section
  head, field grid, meta margin are the deliverables, never a hard-coded
  field order.

**Signatur presence budget (ruled, point 5 included: "demote the
signature").** The Signatur is working data, not an identity mark:

1. Ledger column — stays (mono, margin rule).
2. Edit form — stays, one editable field among Kerndaten.
3. Confirm surfaces — quiet mono after the Titel, identification only.
4. Exposure card / summaries — cut; the article is named by Titel alone.
5. Reader header tab — DEMOTED: the Signatur becomes one row among the
   Akte facts. The bevel cut returns to RESERVED (no licensed context).
6. New surfaces spend no Signatur mark without a ruling.

## Session close + next direction (owner, 2026-08-29)

- **Recompose build wave: PARKED** (direction ruled, see mock-gate verdicts
  above; dispatch when scheduled).
- **Next session, first: an architecture discussion** before more component
  work — how components and the design system are implemented and kept
  maintainable. Owner's open questions: stay HTML + plain CSS? Web
  components? An existing system (shadcn-like)? "The css needs to be
  maintainable."
- **Strategic goal: feature-complete for a FIRST DEPLOYMENT to the
  archivists** — real test + feedback loop outranks further polish. Scope
  planning for that milestone is the other next-session topic.



## Addendum (owner, 2026-08-30) — Postgres is not wholly ephemeral

Asked whether login state may live in the database, the owner ruled:

- **Only the archive files must survive total loss** — media plus Markdown, on
  the WebDAV store. That part of "the server holds only ephemeral data" (see
  *Operations* above) stands.
- **Postgres is not wholly ephemeral.** Admin data — sessions, an audit trail,
  worker jobs — MAY live there. It is the *search index* that is derived and
  rebuildable, not the database around it.
- **Dropping the database is an emergency measure, not routine.** Rebuilding
  the index from the files is routine (the hourly reconcile does it); recreating
  the database throws away everything else in it as well.

Consequences:
- ADR 0018 kept the signed cookie, but on its own merits (no parallel identity
  system, nothing to store or clean up) — the "Postgres is disposable" reason it
  gave is struck.
- Any future admin table (audit trail, capability tokens) is allowed to live in
  Postgres and needs a backup story of its own; it does not have to be
  reconstructible from the files.

## Addendum (owner, 2026-09-19)

- **Backup is outside this project's scope.** The Nextcloud is already backed
  up and the VPS has a rudimentary backup. restic was never an owner
  requirement — it was an earlier agent's idea. There is nothing to build here
  for now. Supersedes the "interim backup story" consequence under Storage and
  the 2026-08-05 backup ruling.
- **The Nextcloud is a Hetzner StorageShare**, not a StorageBox. Every
  occurrence in the repo is corrected to StorageShare.
- **Preview content:** deployment 1 imports a real dump of the old system's
  data once — locally and on the production server — rather than starting from
  an empty or seeded corpus.
- **No in-app feedback channel.** Archivists reach the owner by e-mail.
- **Priority:** technical issues that block the first test deployment come
  first, then iterative improvement.

### Evening rulings (owner, 2026-09-19)

- **Deploy layout:** one folder `/home/admin/bundesarchiv/` holds
  `compose.yml` and all data as bind mounts inside it (canonical,
  thumbnails, pgdata). Postgres is not published on the host. Hostname is
  `archiv.deutscher-pfadfinderbund.de` (already resolves). Watchtower
  deploys `:latest` continuously (hourly). Secrets live in
  `production.env`, never committed.
- **WebDAV mirror to the Nextcloud StorageShare is switched on from day
  one**; canonical stays on the VPS disk.
- **Upload cap is 4 GiB by default** (`BUNDESARCHIV_MAX_UPLOAD_BYTES`); the
  earlier 50 MB was an agent's choice, never a ruling — the archive holds
  videos of several hundred MB.
- **Vocabulary:** Medienart and Dokumenttyp lists are the archivists'
  legacy lists (17 Medienart / 16 Dokumenttyp incl. Urkunde). Every
  Medienart offers all Dokumenttypen until the archivists narrow it.
  Archivists may extend the vocabulary in the future — a door, not
  something built now.
- **Signatur spelling is dictated by the archivists**: the legacy `BA <n>`
  form, with one inner space, is kept verbatim. This supersedes the
  2026-08-07 "no spaces" note above — that note is amended, its text kept
  for the record.
- **Import runs once, locally**, against the CSV export and the media
  backup; the resulting canonical tree is then copied to the VPS.
  Imported items are Published, with audience inherited as Members,
  matching the login-only legacy system. The 196 items without a
  Sammlungsteil go into a Bestand named `Unsortiert`. The legacy `Legacy-ID`
  is kept in custom fields.
- **Bestand stays required for now.** Whether items may not need a Bestand
  is a question for the archivists, not settled here; refactor cost was
  measured at 24 production sites.
- **Preview exposure:** every Keycloak account holder may log in, same as
  today's system.
- **Observability is parked**; issue #15 stays open.
- **Physical-only items are the common case** (1663 of 2506). Several
  physical copies of one Article, each with its own Standort, is a future
  domain wish (issue filed).

## Component architecture rulings (owner, 2026-09-25)

Answers the open question from 2026-08-29 ("the css needs to be maintainable").
Evidence: a throwaway prototype on branch `prototype/component-architecture` —
one field row built three ways, tested in a record card, a narrow form, inside
an extra wrapper, and after an htmx row swap.

- **The stack stays:** Django templates, htmx, plain native CSS. No build step.
- **Web components (shadow DOM) are rejected for styling.** They look the same
  but cost more: two stylesheets per component (the page's control rules beat
  `::slotted()`), a shadow template in every instance's HTML, and a rewrite of
  the design lint and the computed-style walkers. The browser-enforced wall
  covers layout only; control states stay page-wide. Light-DOM custom elements
  for JS behaviour were raised, not ruled.
- **shadcn-style systems are rejected** (React + Tailwind; ADR 0004 and the
  construction law already exclude both).
- **Component model — "owned components":**
  - A component's outer element carries one class named for the component.
    The component styles only its own inside.
  - Pages and compositions set the component's knobs (custom properties) and
    never select inside a component. Knobs inherit through any wrapper, so a
    component works nested anywhere.
  - A lint test enforces the boundary: no composition selector reaches past a
    component's outer class.
  - Facts about a field (width class, Signatur ink) come from the field
    registry, never from CSS keyed on an input's `name`.
  - This amends law C1 ("classes only where semantics cannot discriminate")
    for component roots. The law text changes with the wave that builds it.
- **One section per component, not one file.** Each component's CSS is one
  section of the existing layer file, named like its template. No new
  requests, no `@import`.
- **Order:** a dedicated wave converts every component to the model first,
  before the edit-form recompose build.
- **htmx 4 first, in its own small wave** (before the component wave): plain
  `htmx.min.js` 4.x, not the `htmax` bundle. One extension:
  `browser-indicator` (the tab's own spinner during requests).
- **The upload progress bar is dropped.** htmx 4 sends requests with `fetch()`,
  which reports no upload progress; streaming request bodies work in Chrome
  only. Uploads show a busy state.
- **htmx 2's localStorage page snapshots: ignored.** htmx 2.0.4 keeps copies of
  recent pages in localStorage, past logout. No separate fix; htmx 4 drops the
  mechanism. Reviewers need not report it again.

## Look, navigation and design-rule rulings (owner, 2026-09-26)

Mocks: `docs/design/explorations/2026-09-26-monochrome/` (round 1 `x1–x3`, round 2 `r2-*`),
screen jobs in its `SCREEN-JOBS.md`, rules draft in `RULES-DRAFT.md`.

- **Keep:** the small-caps serif wordmark and the lightweight hairline table. **No scout
  costume** — the audience is adults interested in the Bund's history; a functional tool first.
- **Monochrome.** Gray fills read as "an old, dated Office application"; the violet accent is out
  of place. Black and white, one secondary text ink, hairlines, error red. **No dark-only
  design**: light first, dark is the same tokens inverted.
- **Counts are not important.** No count at display size anywhere.
- **Method:** every screen starts with its job (who, what they try to achieve); every element is
  priced — psychological cost against gain — and high-cost, low-gain elements are cut.
- **Navigation:** a top-level navigation (Archiv · Bestände · Erfassen for archivists) and an
  account area with Abmelden. Supersedes the 2026-08-22 rulings "header carries no identity" and
  "Abmelden lives in the footer".
- **Door page: X3.** Wordmark, one sentence, one solid dark-gray button "Anmelden mit DPB Login".
  No contact line for now.
- **Start page: direction A (Druckschwarz)** — structured, "easy on the eyes and mind"; details
  still to refine. A guiding start page of compartments (search, Bestände, Zeitleiste, Zuletzt
  hinzugefügt); later: archivist Highlights and static Empfehlungen (not built now).
- **Zeitleiste:** nice to have; undated bucket "Unbekannt".
- **Archive list:** must fit the start page's language.
- **Article page: direction C (Schaufenster)** when a large square media preview exists. PDFs and
  scans get their first page rendered as that preview; with no renderable medium the page falls
  back to one column.
- **Serif:** wordmark, section headings and article titles. Everything else sans.
- **Screen sizes:** archivists work mostly on large screens, members and link-holders mostly on
  small ones — balance each size for its users. Three container sizes; each component declares
  per size full / compact / folded / absent. **Phone start page: search plus "Meine Entwürfe"
  only**; browsing (Bestände, Zeitleiste) moves to the Archiv page's folded filter. The round-2
  phone layouts were all rejected: they ignored the smaller space budget.
- **Divide and conquer:** strict design rules first, then tokens, composable components and
  layouts, then pages.
- **Edit-form recompose:** section order E1 (Kerndaten → Beschreibung → Einordnung → Herkunft →
  Medien → Zugriff → Weitere Angaben, all open); the large Titel field is the page heading.
  Runs after Wave C.
- **Navigation architecture (2026-09-27).** Destinations: start, one list, article, the forms,
  door. Everything people pick (Bestand, decade, type, search, Zuletzt, Meine Entwürfe) is a
  preset of the one list; the start page is a composition of presets. Top bar: wordmark,
  "+ Neu …" for archivists, Abmelden — no account name, no "Archiv"/"Bestände" items, no new
  Werkstatt screen. Breadcrumbs on article and form pages show where the article lives; the way
  back to a search is browser Back. New start-page compartment: by type. Highlights later, as
  curated pinned articles — not important now.

## Rulings of 2026-09-27 (design review, legacy data)

- **Look:** the monochrome system "Druckschwarz" is approved and formalized (`DESIGN.md`,
  `docs/design/design-system.md`, register in `docs/design/design-review-law.md`). The door's
  login is a primary button; there is no gray fill.
- **Terms:** keep "Bestand"; the legacy term was "Sammlungsteil"; revisit only on archivist
  feedback.
- **Legacy import:** `pub_date` is the date added (`added_at`); legacy Schlagworte are separated
  by line (and by `--` inside a line), never by word. The earlier word split was a mapping error,
  not an owner ruling.
- **Order:** component waves first; the Medienart / Dokumenttyp rework next.
