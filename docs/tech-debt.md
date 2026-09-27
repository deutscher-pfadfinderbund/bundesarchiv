# Tech-debt ledger

The ONE checked-in debt index, one section per abstraction level. It is an index of debts, not an
essay: an entry says what the pattern is, how to re-measure it, and what deepening it would look
like. The argument for a fix belongs in the issue that graduates from here, not in this file.

**Entry format** (≤ 6 lines, no exceptions — a longer entry is two entries or a GitHub issue):

```
### <n>. <title> — <Strong | Worth exploring | Speculative | in progress (Wn) | done>
- **Indicator:** <a count, a line number, a red-test count> (<date measured>)
- **Evidence:** <file:symbol pointers; "accreted" or the ADR that made it intentional>
- **Deletion test:** <what happens to complexity if the module/pattern goes away>
- **Sketch:** <≤ 3 lines of the deepened interface>
```

The indicator is what makes a trend check re-measurement rather than vibes. Every audit re-measures
every open entry, writes the new number with its date, and closes entries whose pattern is gone
(`audit-architecture` skill, Maintenance duties).

Source: the 2026-09-01 architecture review (two explorers: web layer, domain/persistence spine),
migrated here from `ARCHITECTURE-CANDIDATES.local.md`. Numbering is that review's; new entries
continue it.

## Domain language

No open entries. `CONTEXT.md` matched the code at the 2026-09-01 sweep.

## Module map & packages

### 11. Cross-module private imports mark undeclared seams — Worth exploring
- **Indicator:** 14 imports of 10 private names: 11 in `app/web` (7 modules), 3 in `index` (2)
  (2026-09-25, AST count of `from bundesarchiv… import _name` over `src/`, `_`-modules excluded)
- **Evidence:** `media_views._not_found` ×5; `viewers`, `catalog`, `catalog_views`, `browse_views`,
  `index.models` and `index.scope` each hand one or two private names to siblings. Accreted.
- **Sketch:** promote the deny helper to a public web-level name; each other name goes public on its
  module or moves to its one importer.

### 20. The fixity check reads the repositories' private layout — Worth exploring
- **Indicator:** 5 private imports, all in `persistence/fixity.py` (2026-09-25, the count of #11)
- **Evidence:** `_folder` and `_ulid_of_readme` from both repositories, and `repository._digest` —
  the key layout and the hash the check re-reads (ADR 0019 "Fixity"). Accreted.
- **Sketch:** a named internal layout module beside `_writer` (record folders, README keys, the
  media digest) that both repositories and `fixity` import.

## Interfaces

### 1. Archive handle — one construction site for the canonical store — done
- **Indicator:** store constructed from settings at 8 sites → 1 (2026-09-02)
- **Evidence:** landed as `app/archive.py` (`4b1da8b`), views (`8330afa`), services (`c00a784`).
  Sketched as `persistence.archive`; it lives in `app/` because `canonical()` reads Django settings.
- **Residue:** `tasks.mirror_store()` still builds the optional WebDAV mirror from settings —
  deliberate (jobs carry references, never handles) and recorded in `app/CLAUDE.md`.

### 2. Record card field registry — done
- **Indicator:** the 17-field list declared 6× → 1 (2026-09-02)
- **Evidence:** `9dfa4d0`; `_FIELDS` in `catalog_views.py` now carries label, control, section, seed
  and diff spelling, and the card is a loop over `workbench/_feld.html`.
- **Residue:** `catalog.parse_edit_form` keeps its own enumeration on purpose (ADR 0008: the pure
  leak-sensitive layer must not import the view module).

### 3. EditSurface — one render, one overlay union — done
- **Indicator:** render entry points 5 → 1, post-hoc context keys 3 → 0, `catalog_views.py`
  1425 → 1367 lines (2026-09-02)
- **Evidence:** `EditSurface.of`/`.submitted`/`.render` over `NoOverlay | Conflict | MediaError |
  IndexLag | RemoveConfirm`; the three `_edit_context*` builders, `_rerender_edit` and
  `_rerender_with_custom_removed` are gone, and `stored` is always the SAVED article.
- **Residue:** `catalog.apply_captions` went public — the register's reconstruction has one site now.

### 4. Lift the CAS retry to the layer owning the write cycle — done
- **Indicator:** hand-rolled load-mutate-save loops 2 → 0; `except Conflict` in `app/web` 3 → 2, both
  form saves ADR 0013 keeps there (2026-09-02)
- **Evidence:** `app.articles.update_article` (`Updated | Conflicted | Missing`) over the real write
  shell; `catalog_views._structural_save` and `bulk.apply_bulk` call it; `repository.update()` gone.
- **Residue:** a structural save no longer reuses the Article its gate loaded — one extra README read.

### 5. One authority for the media key layout — done
- **Indicator:** `articles/<ulid>/media/<hash>` declared 3× → 1 (2026-09-02)
- **Evidence:** `cddf3f8` (repository: `media_key`, `find_blob`, `open_media` over a new
  `ObjectStore.open_stream`), `0e07a00` (the seam; `media._MEDIA_KEY`, the settings-derived dev path
  and the drift test all deleted), plus this commit (thumbnails).
- **Residue:** none since ADR 0019 — `find_blob` is gone; the thumbnail job reads the file through
  its Article, and `media_key` takes the ref, not a bare hash.

### 6. FeldWahl — one bulk chooser — done
- **Indicator:** chooser copies 2 → 1, context vocabularies 2 → 1, `data-bulk-wert` hand-typed 8 → 0;
  the placeholder-blanks-the-value bug fixed (2026-09-02)
- **Evidence:** `bulk.feldwahl_context` + `workbench/_feldwahl.html`; `browse_views._BULK_FELD_OPTIONS`
  / `_bulk_collection_options` and `_reject`'s four option keys are gone, and the echo tests are one
  parametrization over `bulk.FIELDS`.
- **Residue:** `layouts.css` still enumerates the 9 targets in its `.chooser:has(…)` rules — CSS
  cannot derive them; the widget-token gate covers the HTML half only.

### 7. BestandChooser — done
- **Indicator:** chooser spelled 3× → 1, orderings 2 → 1 (name-sorted), the refusal string 3 → 1 (2026-09-02)
- **Evidence:** `app/web/bestand.py`; the article form, the Bestand form's parent select, the bulk
  drawer and the rail's name lookups now hold one chooser per request.
- **Residue:** two placeholders survive by design — `options()` refuses its empty value,
  `parent_options()` accepts it (a top-level Bestand has no parent).

### 8. Trefferliste — name the results view-model — Worth exploring
- **Indicator:** ~20-key untyped dict; 6 `type: ignore` in `browse_views.py` (2026-09-02)
- **Evidence:** `_results_context` + seven pure helpers inside the route; `page: object` although
  `SearchPage` is public. ~25 of ~60 workbench tests are pure link-algebra assertions each paying
  Postgres + corpus + rebuild + HTTP + HTML grep.
- **Sketch:** pure `results_view(parsed, page: SearchPage, …) -> Trefferliste` frozen dataclass;
  the security-spine and HTMX render-fork tests stay on the route per the testing razor.

### 9. CollectionTree — deepen the resolver's input — Worth exploring
- **Indicator:** the load + `resolve_chain` + fail-closed ceremony copied at 6 sites, 4 different
  fail-closed policies (2026-09-01)
- **Evidence:** `article_auth`, `media_views`, `index/indexer` (the web forms now resolve through
  `bestand.by_ulid`). ADR 0001's one-pure-function contract holds; it is the ceremony around it that
  is copied. `media_views` re-reads every Collection README per byte-range.
- **Evidence** (Caution, 2026-08-22 attempt, branch `arch/pure-store`, abandoned):
  removing a constructor `mkdir` opened a bootstrap gap (virgin deploy 500s).
  A top-level `app/collections.py` import hit an `AppRegistryNotReady` cycle.
  An import-graph test named for "layer order" left `app`/`app.web` unconstrained.
- **Sketch:** `CollectionTree` value object — `chain_for(id) -> ResolvedChain`,
  `descendants_of(id) -> frozenset`; built once per operation by `CollectionRepository.tree()`.

### 10. `create_article` stops restating the Article shape — Worth exploring
- **Indicator:** 17-parameter signature (archive + 16 keyword fields); the field list restated a
  third time in `copy_article` (2026-09-02)
- **Evidence:** `app/articles.py` forwards 1:1 to `identity.create_article`. A DTO in all but name —
  ADR 0008 territory.
- **Deletion test:** fails as written (pure forwarding).
- **Sketch:** `create_article(archive, article: Article)`; the view mints the valid-by-construction
  Article, and `copy_article` becomes `replace(source, ulid=new_ulid(), …)`.

### 13. `scanned` is derivable from `focusable` — Speculative
- **Indicator:** 1 pinned relation, `scanned == focusable - {"gruppen"}` (2026-09-02)
- **Evidence:** `catalog_views._FIELDS` declares both columns;
  `test_catalog_edit.test_scanned_is_the_focusable_spine_minus_the_one_declared_exception` pins the
  relation. A test pinning a derivation is the smell an owning interface would remove.
- **Sketch:** drop the `scanned` column; derive the GET spine from `focusable` minus a named
  exception set. Follow-up from W2; low value until a second exception appears.

### 17. Single-writer assumption fails silently — Speculative
- **Indicator:** 0 boot-time checks (2026-09-19)
- **Evidence:** ADR 0013 states the deploy rule only; source `ARCHITECTURE-REVIEW.md.local` R7
  (2026-07-19, clean review).
- **Sketch:** a boot-time assertion or store-level advisory lock so a second app process fails loud.

### 18. The upload path buffers whole files in RAM — done
- **Indicator:** upload peak memory = file size (2026-09-19) → flat: after a warm-up upload, the
  `tracemalloc` peaks of a 4 MiB upload, a 32 MiB upload and a repeat of the 32 MiB file (the
  reuse path) lie within 1 MiB of each other (2026-09-25); RSS not measured
- **Evidence:** ADR 0019 "Streaming upload": `ArticleRepository.add_media` takes a seekable stream,
  hashes it in 1 MiB chunks and stores it with `create_large`; the view hands it the upload file.
  Pinned by `test_catalog_medien.test_hochladen_memory_does_not_grow_with_the_file`.

## Implementation patterns

### 19. Compositions style inside components — done
- **Indicator:** 0 composition reach-ins, the lint's allow-list deleted (2026-09-26; 44 → 37 → 1 → 0
  over WAVE-C); 0 wrapper-sensitive knob sites (Wave R U1 cut the record card's `.fach > .field`; the
  form-sheet sets `--field-font` on its own root)
- **Deletion test:** pages set knobs only; a wrapper or a new field changes no composition CSS

### 14. `catalog_views.py` is the wave's dumping ground — Strong (pointer entry)
- **Indicator:** 1380 lines (2026-09-02, after #7 carved the chooser out), up from ~970 before the
  registry landed
- **Evidence:** routes, the field registry, the structural-save retry, the media drawer and the
  Bestand chooser all live here. Accreted.
- **Sketch:** no separate fix — #3 (EditSurface), #4 (CAS lift) and #7 (BestandChooser) each carve
  out a piece. Re-measure the line count after each.

### 15. Archivist route gate spelled many ways — Speculative
- **Indicator:** 8 hand-written `request.method != …` re-checks in `app/web` (2026-09-02)
- **Evidence:** `_load_gated` omits method checking, so callers re-append it. Related: `viewer_of`
  resolves up to 4× per request while the attach-once `request.viewer` pattern
  (`dev.DevViewerMiddleware`) sits unused in production.
- **Cost class:** tidiness, not safety — `test_leak_matrix._CONTRACT` exhaustiveness already makes a
  forgotten gate loud.
- **Sketch:** an `@archivist_route(method=…, needs_article=True)` decorator seam.

### 16. Shallow wrappers that fail the deletion test — Speculative
- **Indicator:** 2 one-line pass-throughs (2026-09-02, `_collection_options` went with #7)
- **Evidence:** `catalog_views._audience_label:556`, `collection_views._sichtbarkeit_label:230`.
- **Deletion test:** fails — inlining each removes a name and adds nothing.

### 20. Variants in disguise (law C2) — Strong
- **Indicator:** 3 open in the monochrome mock system, 5 in the app (2026-09-27, after the `.badge` and
  empty-Signatur fixes).
- **The pattern:** a modifier class that sets a component's own properties (`.button-danger`) instead
  of a context that re-points roles or knobs and works on any component (`.danger` re-points
  `--ink`). Fixed 2026-09-27: `.button-danger`, `.menu-destructive`, the red built into `.remove`
  and the chip × — all now the one `.danger` context; `.facts-quiet`, the set-apart register
  label and the `--section-head-ink` / `--register-ink` knobs — all now the one `.quiet` context;
  `.button-sso` gone (owner: the door's login is just a primary button). Wave K1: `.badge.entwurf`,
  the boxed `#dirty-flag` and the Titelbild rule — now the one `.mark`; the Bestand form's quiet
  facts — now `.quiet`; the record row's `<details class="menu">` — now the one popover menu, its
  Löschen / Verwerfen under `.danger`. Owner 2026-09-27: `.badge` deleted (no production user left);
  the empty Signatur shows nothing (no dash placeholder).
- **Open, mock system** (`docs/design/explorations/2026-09-26-monochrome/system/system.css`):
  - `.button-primary`: a variant. Candidate: an inverse context (swap `--ground` / `--ink`); cost:
    the button must paint its background with `--ground`, and the hover outline needs an edge.
  - search sentence `.is-minor` (encodes "folds on S"; structure can say it: every slot after the
    first) and `.is-more` (a different element, so a part: `.search-sentence-more`). `.is-set` is
    state and stays exempt.
- **Open, app** (Wave T report, 2026-09-27; Wave T fixed `button.danger`, the Signatur tab, the
  amber ENTWURF mark and the Titelbild inversion):
  - `.primary`: a button variant (candidate: an inverse context). Owner 2026-09-27: settle it in the
    list-page wave, together with the facet inversion below.
  - `.facet li:has(> [aria-current])`: an inversion register row 3 does not license.
  - lines row 14 forbids: the ledger's covering rules, its header underline; the dashed
    `.column dd` decoration (row 6 licenses dashes only for hollow slots).
  - `.pane > div` framed while the pane question is suspended (row 10).
  - Wave K1 found, outside its fence: the detail page's `<small>Nur intern</small>` (the note
    "intern" instead); the list page's chip and facet ✕ are text glyphs, not the remove control;
    `components/empty_state.html` draws a dashed frame (row 6); the Datierung parse error is
    English. (The create step marks its required Bestand since Wave R U4.) (`_reach_edit_folded_open` went with the folds,
    Wave R U1.)
- **Sketch:** fix each in the component wave that converts its component; a lint candidate: a
  selector on a non-root class that sets a non-custom property on a component root.
- **A context reaches only what reads the role:** `color: inherit` passes the resolved colour, so a
  part that should answer a context binds itself to `var(--ink)` (the menu entries had to).

## Tests

### 12. Pre-existing e2e failures on main — done
- **Indicator:** 3 red journeys (2026-09-02); 0 red, 44/44 green (2026-09-26, the anchor-insets
  fix for #53)
- **Evidence:** `test_control_rows_compute_one_height_source`,
  `test_the_control_row_walk_sees_what_the_screens_compose`,
  `test_overlays_stay_inside_the_viewport` — the `+ Neu…` / `Mehr…` panels start off-viewport
  (-98px) on every screen. Verified identical on untouched `main`, so not wave-introduced.
- **Cost class:** defect (UI); it also blocks e2e as a signal — a wave cannot tell its own
  regressions from this baseline until it is fixed.

### 21. The e2e walkers hard-code what an overlay is — done
- **Indicator:** 3 places spelled "overlay = `details:has(> ul)`" (Wave T, 2026-09-27): the count
  selector, the walk JS and the control-row panel filter in `tests/e2e/`. 1 (Wave K1, 2026-09-27):
  `_pages.OVERLAY_MECHANISMS`, which every walker reads; the next mechanism is one line.
- **Also:** the design lint parses CSS that is formatted by hand (no CSS formatter); a mis-wrapped
  rule can slip past it. Watch for a second occurrence before adding a formatter.

## Process law

- **Row budget friction** — `ROW_MAX_CHARS=220` forced 4 rewrites of one interface-rich row (bestand.py, 2026-09-03, landed at exactly 220). One occurrence = instance, not evidence; if a second row fights the cap, investigate the budget (wrap the interface segment vs raise) per the framework-health rule. Indicator: rows within 10 chars of cap: 1.

## Build & CI

CI runs under 60s with no caching machinery (owner ruling); keep it that way.

### 22. Parallel worktrees share one test database — Instance
- **Indicator:** 1 collision (2026-09-28): a gate in one worktree failed 1743 setups with
  `DROP DATABASE "test_bundesarchiv"` refused while another worktree's gate held the database.
- **Cause:** every worktree's Postgres-backed suite uses the same test database name.
- **Sketch:** derive the test database name from the worktree (for example a suffix from the
  checkout path) in the test settings, so parallel gates never share one; until then, run gates
  one at a time.
