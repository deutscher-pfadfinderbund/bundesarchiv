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
- **Indicator:** 11 private names imported across 5 web modules (2026-09-02)
- **Evidence:** `_not_found` ×4, `_is_archivist` ×3, plus `catalog._parse_audience`,
  `catalog_views._SICHTBARKEIT_OPTIONS`, `browse_views._body_paragraphs`,
  `browse_views._serve_static`. Accreted; each is a seam nobody named.
- **Deletion test:** passes — the importers would have to state what they actually need.
- **Sketch:** promote the deny helper and the archivist gate to public web-level names; the rest
  falls out of #2 and #7.

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
- **Residue:** `find_blob` still scans `articles/` — there is no hash→key index, and one would be a
  second source of truth about where blobs live.

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

## Implementation patterns

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

## Tests

### 12. Pre-existing e2e failures on main — defect (UI), open
- **Indicator:** 3 red journeys (2026-09-02)
- **Evidence:** `test_control_rows_compute_one_height_source`,
  `test_the_control_row_walk_sees_what_the_screens_compose`,
  `test_overlays_stay_inside_the_viewport` — the `+ Neu…` / `Mehr…` panels start off-viewport
  (-98px) on every screen. Verified identical on untouched `main`, so not wave-introduced.
- **Cost class:** defect (UI); it also blocks e2e as a signal — a wave cannot tell its own
  regressions from this baseline until it is fixed.

## Process law

- **Row budget friction** — `ROW_MAX_CHARS=220` forced 4 rewrites of one interface-rich row (bestand.py, 2026-09-03, landed at exactly 220). One occurrence = instance, not evidence; if a second row fights the cap, investigate the budget (wrap the interface segment vs raise) per the framework-health rule. Indicator: rows within 10 chars of cap: 1.

## Build & CI

No open entries. CI runs under 60s with no caching machinery (owner ruling); keep it that way.
