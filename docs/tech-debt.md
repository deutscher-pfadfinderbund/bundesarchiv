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
continue it. #31–48 come from the 2026-10-01 cleanup review (its W/A/P ids are in the evidence lines).

## Domain language

### 30. Who may read a Bestand's name is unruled — Worth exploring
- **Indicator:** 1 site shows any Bestand's name, or an unknown ulid, to a Member: the list's Bestand slot (2026-10-01)
- **Evidence:** `browse_views.py` slot label from `collection_chooser.names()` (all Collections); `article_auth.py` asserts "names are member-safe" without a ruling. 2026-10-01: OK for now, revisit
- **Deletion test:** n/a — a missing rule, not a module
- **Sketch:** decide with group access / the policy rework; if names are scoped, the slot label comes from the viewer-scoped facet only

### 31. The publish precondition lives in the view, spelled three ways — Worth exploring
- **Indicator:** 3 spellings of "the chain must resolve" (2026-10-01, W4)
- **Evidence:** `catalog_views` edit POST (submitted Bestand), publish route (stored one), status options (`inherited is None`). Bite: `236e525` (published anyway), `b8244dd` (2nd copy).
- **Sketch:** one pure `can_publish(chain)` in the domain; the three callers ask it.

### 32. "Public" and "Archivist" have several definitions — Speculative
- **Indicator:** 3 definitions of Public; 118 tests build `Public()`; the form still offers "Öffentlich" (2026-10-01, A5)
- **Evidence:** `viewer.py:14,30`, `oidc.py:20`, `anonymous_gate.py:56-61`, `vocab.py:141,177`. Archivist is a group in `CONTEXT.md`, a realm role in code.
- **Sketch:** Public stays for future link access. Docs only: `CONTEXT.md` states both terms as built.

### 33. Medienart / Dokumenttyp: fixed lists in code, free text by ruling — Worth exploring
- **Indicator:** pair rules restated in 8 sites over 3 modules; 2 Dokumenttyp-option routes, 5 param aliases (2026-10-01, P5/W5)
- **Evidence:** `catalog.py:149-160`, `bulk_views.py`, `bulk.py`, `catalog_views.py:995-1009`; `vocab.py` in `app/web` is imported by a command and injected into `legacy.py`. Every pair is valid today, so the refusal branches never run.
- **Deletion test:** free text deletes all 8 pair rules and both routes; `vocab` lists become suggestions. `media_type` still names Medienart and MIME type: rename one.
- **2026-10-21:** Art becomes several independent questions (#72 folds in). The design waits on the archivists.

## Packages

### 11. Cross-module private imports mark undeclared seams — Worth exploring
- **Indicator:** 11 imports of 8 private names: 5 in `persistence/fixity.py`, 5 in `index`, 1 in `app/web`
  (2026-10-01, better; 14 / 10 names on 2026-09-25; same AST count of `from bundesarchiv… import _name`).
  2026-10-21, better: 2 cross-module, both from `index/scope.py` (`_viewer_scope`, `_scope_columns`); the strict
  count is 6 imports of 4 names, the other 4 take the private `_front_matter`/`_change` modules inside `persistence`.
  The 5 `module._name` reaches in `app/web/legacy_params.py` (`browse_views`, `landing`) are not counted.
- **Evidence:** `media_views._not_found` ×5; `viewers`, `catalog`, `catalog_views`, `browse_views`,
  `index.models` and `index.scope` each hand one or two private names to siblings. Accreted.
- **Sketch:** promote the deny helper to a public web-level name; each other name goes public on its
  module or moves to its one importer.

### 34. Field labels are declared twice, "Typ" derived three ways — Worth exploring
- **Indicator:** 6 labels in both `card.FIELDS` and `bulk.FIELDS`, a third time in `bulk.apply_field` (2026-10-01, W6)
- **Evidence:** `card.py:138-293`, `bulk.py:61-71,153-168`, `ledger.py:39`, `browse_views.py:264,650`. Bite: `5c902a2`.
- **Indicator 2026-10-21, partly better:** `card.LABELS` is one lookup (`reading.py`, `suggestions.py`); `bulk.FIELDS` and `ledger.COLUMNS` still restate labels.
- **Sketch:** one label source both registries read; one rule for "Typ".

### 36. Group strings have no owner — Strong
- **Indicator:** exact-equality group match in 3 places; 0 value types (2026-10-01, A1)
- **Evidence:** `access.py:72-75`, `scope.py:74-78`, `query.py:477-483`, `oidc.py:34`. `/Orden St. Georg/Komturei` does not satisfy `/Orden St. Georg` (probe). No group audience in data yet.
- **Sketch:** a `Group` value type: one parse of the claim, one match rule.

### 37. "What a non-Archivist may see" is declared in 7 places — Strong
- **Indicator:** 7 declarations, 3 drift guards, 2 unguarded; 2 contradict on `audience` (2026-10-01, A2; not re-measured 2026-10-31)
- **Evidence:** `domain/access.py:ARCHIVIST_ONLY_FIELDS`, `index/indexer.py:_BUILDER_FIELDS`, `index/query.py:HEADLINE_FIELDS`/`_SUGGESTED_COLUMNS`, `index/models.py:archivist_text`. Bite: `91900b3` (group names leaked), `ed4c054`.
- **Indicator 2026-10-21, worse:** `query.HEADLINE_FIELDS` and `query._SUGGESTED_COLUMNS` declare member-visible subsets, each guarded by its own leak suite (`test_leaks_headlines.py`, `test_leaks_suggestions.py`), neither derived from `ARCHIVIST_ONLY_FIELDS`.
- **Sketch:** one owner of the visible attributes; the Python/SQL scope pair stays two encodings.

### 39. Mirror push overwrites a remote README without checking its token — Worth exploring
- **Indicator:** 1 unchecked path; only reconcile compares (2026-10-01, P6; not re-measured 2026-10-31)
- **Evidence:** `app/mirror.py`: `_replaceable` calls `write_atomic` without comparing the remote version; `ReconcileReport.changed` is the only comparison. Bites when the StorageShare is canonical (hand edits).
- **Sketch:** push compares the remote version token first, as reconcile does.

### 40. Persistence trusts a ulid as a key segment — Speculative
- **Indicator:** `is_valid_ulid` checked 6× in web, 0× in persistence and domain (2026-10-01, P8)
- **Evidence:** `repository.py:222`, `collections.py:103`.
- **Indicator 2026-10-21, stable:** 6 call sites in `app/web`, 0 in persistence and domain.
- **Sketch:** validate once where a key is built.

## Interfaces

### 26. A media route re-derives the version its own save started from — Worth exploring
- **Indicator:** 1 site, `catalog_views._media_surface` (`version == held + 1`) (2026-10-01, stable; bit twice more: `eb71b4c`, `1452c38`)
- **Evidence:** `app/result.py::Updated` carries only the new version; `app/articles.update_article`
- **Deletion test:** with `Updated.base`, the ADR 0013 counter arithmetic leaves the web layer
- **Sketch:** `Updated(article, version, base)`; `_media_surface` advances iff `base == held`

### 8. Trefferliste — name the results view-model — in progress (Wave LIST)
- **Indicator:** ~20-key untyped dict; 6 `type: ignore` in `browse_views.py` (2026-09-02). Wave LIST:
  the `type: ignore`s are gone (`page: SearchPage`) and the ledger's rows and columns are typed
  (`ledger.py`); the rest of `_results_context` is still a dict. 0 `type: ignore` (2026-10-01, stable;
  0 on 2026-10-21).
- **Evidence:** `_results_context` + seven pure helpers inside the route; `page: object` although
  `SearchPage` is public. ~25 of ~60 workbench tests are pure link-algebra assertions each paying
  Postgres + corpus + rebuild + HTTP + HTML grep.
- **Sketch:** pure `results_view(parsed, page: SearchPage, …) -> Trefferliste` frozen dataclass;
  the security-spine and HTMX render-fork tests stay on the route per the testing razor.

### 9. CollectionTree — deepen the resolver's input — Worth exploring
- **Indicator:** `resolve_chain` called at 3 sites in 2 modules (2026-10-06, better; 5 in 4 on 2026-10-01, 6 on 2026-09-01);
  the 2 web `_collections` copies now go through `CollectionChooser.chain_of` (Wave CLEAN, 2026-10-01);
  the indexer builds it through one helper, `_collection_lookup` (Wave CANON, 2026-10-01)
- **Evidence:** `collection_chooser` and `index/indexer` hold the copies (the web forms resolve through
  `collection_chooser.by_ulid`; `article_auth` and `media_views` no longer copy). ADR 0001's one-pure-function contract holds; it is the ceremony around it that
  is copied. `media_views` re-reads every Collection README per byte-range.
- **Evidence** (Caution, 2026-08-22 attempt, branch `arch/pure-store`, abandoned):
  removing a constructor `mkdir` opened a bootstrap gap (virgin deploy 500s).
  A top-level `app/collections.py` import hit an `AppRegistryNotReady` cycle.
  An import-graph test named for "layer order" left `app`/`app.web` unconstrained.
- **Sketch:** `CollectionTree` value object — `chain_for(id) -> ResolvedChain`,
  `descendants_of(id) -> frozenset`; built once per operation by `CollectionRepository.tree()`.

### 10. `create_article` stops restating the Article shape — Worth exploring
- **Indicator:** 17-parameter signature (archive + 16 keyword fields); the field list restated a
  third time in `copy_article` (2026-10-01, stable). P1 adds: a new text field = ~14 edits in 9 files,
  a faceted one 20 files; the round-trip test fills 10 of 18 fields
- **Evidence:** `app/articles.py` forwards 1:1 to `identity.create_article`. A DTO in all but name —
  ADR 0008 territory.
- **Deletion test:** fails as written (pure forwarding).
- **Sketch:** `create_article(archive, article: Article)`; the view mints the valid-by-construction
  Article, and `copy_article` becomes `replace(source, ulid=new_ulid(), …)`.
- **Gate first (G1, 2026-10-02, before CLASSIFY):** one Article with every field set
  adversarially, generated from `dataclasses.fields(Article)`, survives README encode→decode,
  `copy_article` and an unchanged edit-form save; a field the generator cannot fill fails.

### 13. `scanned` is derivable from `focusable` — Speculative
- **Indicator:** 1 pinned relation, `scanned == focusable - {"gruppen"}` (2026-10-01, stable)
- **Evidence:** `card.FIELDS` declares both columns;
  `test_catalog_edit.test_scanned_is_the_focusable_spine_minus_the_one_declared_exception` pins the
  relation. A test pinning a derivation is the smell an owning interface would remove.
- **Sketch:** drop the `scanned` column; derive the GET spine from `focusable` minus a named
  exception set. Follow-up from W2; low value until a second exception appears.

### 17. Single-writer assumption fails silently — Speculative
- **Indicator:** 0 boot-time checks (2026-10-01, stable; the index writer has its own advisory lock)
- **Evidence:** ADR 0013 states the deploy rule only; source `ARCHITECTURE-REVIEW.md.local` R7
  (2026-07-19, clean review). A management command that writes canonical data is a second process
  too: `WRITER_LOCK` is a `threading.Lock`, so it does not serialize against gunicorn; the README
  relayout (2026-10-16) ran with the app stopped.
- **Sketch:** a boot-time assertion or store-level advisory lock so a second app process fails loud.

### 58. The `__Host-` login cookies can be shadowed through Django's cookie parser — Speculative
- **Indicator:** `parse_cookie("\u2000__Host-access=x")` returns `{"__Host-access": "x"}`, a later duplicate wins (2026-10-21, Django 6.1.1)
- **Evidence:** Django's `http.cookie.parse_cookie` (`key.strip()`); `viewers.login_cookies`. Needs control of a host on the registrable domain (Keycloak's sibling)
- **Deletion test:** n/a: a limit of the prefix, ruled out for the CSRF cookie by dropping its `__Host-` name (ADR 0025)
- **Sketch:** ignore a login cookie whose raw name in the `Cookie` header is not its parsed name; or wait for Django to stop stripping

### 59. Each test-only port override needs its own production refusal — Speculative
- **Indicator:** 2 overrides (`BUNDESARCHIV_INDEX`, `BUNDESARCHIV_REALM`), each refused by hand in `index/wsgi.py` (2026-10-21)
- **Evidence:** `app/archive.py` reads `BUNDESARCHIV_INDEX`, `app/web/viewers.py` reads `BUNDESARCHIV_REALM`. Bite: `5c4377ee` shipped the realm port without its refusal; `547a1e01` added it the same day.
- **Sketch:** `tests/app/web/test_deploy_settings.py` derives its list from every `BUNDESARCHIV_*` override that prod settings do not define.

## Implementation patterns

### 27. The thumbnail root is resolved in six places — Worth exploring
- **Indicator:** 6 `Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)` sites (2026-10-06; 5 on 2026-10-01 — `app/stats.py` joined; 6 on 2026-10-21, stable)
- **Evidence:** `app/tasks.py`, `app/stats.py`, `app/web/media.py`, `import_legacy`, `browse_views`, `rebuild_thumbnails`
- **Deletion test:** one `thumbnails.root()` removes five copies of the settings lookup
- **Sketch:** `thumbnails.root() -> Path`; callers pass nothing

### 14. `catalog_views.py` is the wave's dumping ground — Strong (pointer entry)
- **Indicator:** 1009 lines, 12 routes (2026-10-01, better; 1380 on 2026-09-02, ~970 before the
  registry landed)
- **Evidence:** routes, the field registry, the structural-save retry, the media drawer and the
  Bestand chooser all live here. Accreted.
- **Sketch:** no separate fix — #3 (done) (EditSurface), #4 (done) (CAS lift) and #7 (done) (CollectionChooser) each carve
  out a piece. Re-measure the line count after each.

### 15. Archivist route gate spelled many ways — Strong
- **Indicator:** 15 hand-written `request.method != …` re-checks in `app/web` (2026-10-01, worse; 8 on
  2026-09-02); 13 `isinstance(…, Archivist)` sites in 9 modules (A8: the policy rework's real cost).
  2026-10-21, worse: 18 method checks (16 on 2026-10-07), a third gate shape in `suggestions.py` (Public or non-GET); 12 sites in 7 modules
- **Evidence:** each write route gates itself; a forgotten gate is open to every Member at runtime
  (only the leak matrix catches it, in tests). 2026-10-01: archivist-only is the default.
- **Sketch:** a middleware after the anonymous gate makes every route archivist-only; a view opts
  wider with `@member` (and names its methods, e.g. `@member(methods=("GET",))`), the pattern of
  Django's `LoginRequiredMiddleware` + `@login_not_required`. A forgotten decorator fails closed.

### 16. Shallow wrappers that fail the deletion test — Speculative
- **Indicator:** 2 pass-throughs (2026-10-11, same as after Wave CLEAN; 3 on 2026-10-01)
- **Evidence:** `card._audience_label`, `app/reindex.py` (3 lines, 1 caller; `indexer.rebuild` owns the page-vector
  recompute, 2026-10-11). `article_auth.resolve_visible_article` inlined (Wave CLEAN, 2026-10-01).
- **Deletion test:** fails — inlining each removes a name and adds nothing.

### 20. Variants in disguise (law C2) — Strong
- **Indicator:** 3 open in the monochrome mock system, 5 in the app (2026-10-01, stable; no CSS change
  to the listed items since 2026-09-27).
- **The pattern:** a modifier class that sets a component's own properties (`.button-danger`) instead
  of a context that re-points roles or knobs and works on any component (`.danger` re-points
  `--ink`). Fixed 2026-09-27: `.button-danger`, `.menu-destructive`, the red built into `.remove`
  and the chip × — all now the one `.danger` context; `.facts-quiet`, the set-apart register
  label and the `--section-head-ink` / `--register-ink` knobs — all now the one `.quiet` context;
  `.button-sso` gone (the door's login is just a primary button). Wave K1: `.badge.entwurf`,
  the boxed `#dirty-flag` and the Titelbild rule — now the one `.mark`; the Bestand form's quiet
  facts — now `.quiet`; the record row's `<details class="menu">` — now the one popover menu, its
  Löschen / Verwerfen under `.danger`. 2026-09-27: `.badge` deleted (no production user left);
  the empty Signatur shows nothing (no dash placeholder).
- **Open, mock system** (`docs/design/explorations/2026-09-26-monochrome/system/system.css`):
  - `.button-primary`: a variant. Candidate: an inverse context (swap `--ground` / `--ink`); cost:
    the button must paint its background with `--ground`, and the hover outline needs an edge.
  - search sentence `.is-minor` (encodes "folds on S"; structure can say it: every slot after the
    first) and `.is-more` (a different element, so a part: `.search-sentence-more`). `.is-set` is
    state and stays exempt.
- **Open, app** (Wave T report, 2026-09-27; Wave T fixed `button.danger`, the Signatur tab, the
  amber ENTWURF mark and the Titelbild inversion):
  - `.primary`: a button variant (candidate: an inverse context). 2026-09-27: settle it in the
    list-page wave, together with the facet inversion below.
  - `.facet li:has(> [aria-current])`: an inversion register row 3 does not license.
  - lines row 14 forbids: the dashed `.column dd` decoration (row 6 licenses dashes only for hollow
    slots). (The ledger's covering rules and header underline went with the list wave, 2026-09-29.)
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

### 29. The gallery has no lead without a picture — Worth exploring
- **Indicator:** 0 gallery states render `.platte:has(.blank)` (2026-10-01, stable)
- **Evidence:** every e2e corpus file now has a thumbnail (PDFTHUMBS); `static/detail.css`
- **Deletion test:** a non-renderable corpus file (audio/video) brings the state back
- **Sketch:** one audio file on a corpus article + a `detail-audio` gallery state

### 55. Tests monkeypatch our own code — Strong
- **Indicator:** `monkeypatch.setattr` on a `bundesarchiv` name: `tests/app` 56, `tests/app/web` 48, `tests/persistence` 2, `tests/e2e` 0 (2026-10-11, AST count); `tests/app` 48 once the page-text shells moved, then `tests/app` 47 and `tests/app/web` 47 once the page-text tests dropped theirs (2026-10-11); `tests/app` 25, `tests/app/web` 53, `tests/persistence` 2 once the jobs received their dependencies, 0 `_DEBT` patches on `app.tasks` left (2026-10-18); `tests/app` 11, `tests/app/web` 48, `tests/persistence` 2 once the tests read the in-memory queue, 0 patches of an `enqueue_*` name left (2026-10-18); `tests/app` 5, `tests/app/web` 43, `tests/persistence` 2 once the index sits behind a port, 0 patches on `after_write` left (2026-10-18); `tests/app/web` 30 once the login realm sits behind a port, 0 patches on `keycloak`, `auth_views` or the `viewers` realm calls left (2026-10-18); `tests/app/web` 29 once dev and the tests log in through the dev realm, 0 patches on `viewers` left (2026-10-18); `tests/app` 4, `tests/app/web` 22, `tests/persistence` 0 once the pager, media, pixel-cap, retry and fsync tests dropped theirs: `_DEBT` sites 16 → 6, all sites 36 → 26 (2026-10-21)
- **Evidence:** `writer-discipline` skill, "Functional core, imperative shell"; what is left (2026-10-21): the leak matrix's 4 (`browse_views.search`, `start`), `vocab.MEDIA_TYPE_DOCUMENT_TYPES` (GitHub #72), `Archive.canonical` in `recording_store`
- **Deletion test:** a test runs the real shell over `Archive.of(...)` and the in-memory queue; a renamed function no longer leaves a patch passing vacuously
- **Sketch:** removed when the module is touched; a later wave may sweep the rest

### 57. `client_as` without the corpus settings runs as anonymous — Worth exploring
- **Indicator:** 0 web test modules call `client_as(` without `corpus`/`settings_for` (2026-10-17); 1 found and fixed (`test_legacy_params`, `d836debf`)
- **Evidence:** `tests/app/web/_fixtures.py::client_as` mints dev-realm tokens under the settings in force, but the realm and the gate-off switch come only from the corpus settings; with the key but no `BUNDESARCHIV_REALM` the tokens go to Keycloak, are refused, and the test sees the 200 door page
- **Sketch:** `client_as(viewer)` fails loudly when the dev realm is not configured, so a viewer-less run cannot pass vacuously. Partly built (2026-10-18, ADR 0025): `viewer_cookies` asserts the dev key; the realm and the gate are still unchecked

### 52. German FTS ranking is untuned — Speculative
- **Indicator:** 0 relevance judgements on real queries; config `german` fixed by ADR 0011 (2026-10-06)
- **Evidence:** `index/query.py` ranking; parked on GH #19 until real data exists. Trigger: the archivists' first real searches
- **Sketch:** collect misranked queries, then weights, a synonym or unaccent dictionary, or a trigram fallback

### 54. A save conflict re-shows the loser's per-file fields over the winner's media — Strong
- **Indicator:** 2 per-file fields (caption, alt) restored from a conflict without a base comparison (2026-10-07)
- **Evidence:** `EditSurface.of(...).submitted(...)` -> `apply_media_fields`: the re-shown form overlays the losing editor's caption and alt onto the winner's media, so a second save can silently undo the winner's per-file edits
- **Sketch:** carry the base version into the conflict re-render and overlay only the fields the loser changed against it
- **Tracked:** issue #91

### 60. `test:affected` runs no Postgres-backed web test for a template-only diff — Worth exploring
- **Indicator:** `scripts/affected.py` RULES: `app/web/**/*.html|css|js` selects `test:gallery` and `test:e2e` only (2026-10-21)
- **Evidence:** the 2026-10-21 template refactor wrote `tests/app/web` by hand (1464 passed); those tests render the templates
- **Deletion test:** a template edit that breaks a rendered page asserted in `tests/app/web` goes red in `test:affected`
- **Sketch:** the `UI` rule also names `test:db`

### 61. No stock computed-style probe for pixel-neutral waves — Speculative
- **Indicator:** each writer writes ~50 throwaway lines over `tests/e2e/_gallery.py` states (2026-10-21, one wave)
- **Evidence:** `dispatch-wave` skill asks for the probe; no tool exists
- **Deletion test:** a wave runs one command and gets a before/after computed-style diff
- **Sketch:** a `tests/e2e` helper dumping computed styles per gallery state

### 62. Private test helpers other suites want — Worth exploring
- **Indicator:** 3 (2026-10-21): `_BLANK_FORM` (`tests/app/web/_fixtures.py`), `_article_whose_collection_chain_is_broken` (`test_catalog_actions.py`), the "orphan" fixture (`test_media.py`)
- **Evidence:** `_BLANK_FORM` is a valid edit-form POST; a missing required field fails silently when only the stored record is asserted
- **Deletion test:** one shared form and one broken-chain fixture replace the copies
- **Sketch:** public names in `_fixtures.py`

### 63. Template facts declared twice after the column frame — Worth exploring
- **Indicator:** 3 pairs (2026-10-21): the crumbs `nav` in `workbench/detail.html` and `article_edit.html` besides `column.html`; the `filter_params` hidden-input loop in `_header.html` and `_search_field.html`; the `components_demo.html` menu sample (link entries) against the real header menu (`popovertarget` buttons)
- **Evidence:** `workbench/column.html`, `workbench/_header.html`, `workbench/_search_field.html`
- **Deletion test:** one include per fact; the demo shows the real entries
- **Sketch:** a crumbs include and a filter-params include

## Process law

- **The second caller copies a decision instead of moving it** — 10 findings in the 2026-10-01 review (#9, #49 (done), #31, #33–37, #43–44 (done)). Adopted: `writer-discipline` skill, "One owner per decision" (`e488814`); gated where mechanical by `tests/test_structure.py`. Indicator: 10 copies found (2026-10-01).

- **Left (2026-10-01):** each state rebuilds the corpus (`live_server` → `transactional_db` truncates the index), so the full run is ~9% slower (135 s) and `test:gallery-diff` takes ~4.5 min; a module-scoped corpus would cut both but changes the isolation `edit-conflict` relies on. The diff task's first version compared only the alpha band (always "identical"); fixed 2026-10-01 (RGB). A re-check of the rebuild (`f45b8db` vs `91a500b`) then showed 35 changed PNGs, all from the old single-test run leaking a bulk edit's author ("Sammel-Autor") into later states; per-state isolation removed that leak, so the new renders are the correct ones.
### 23. Tests pin UI copy and markup — Strong
- **Indicator:** 109 `"…" in body`-style asserts in `tests/app`, 201 `get_by_*`/`locator(` calls in `tests/e2e` (2026-10-01; new grep, not comparable with 188 / 53 of 2026-09-30 — baseline reset)
- **Evidence:** 2026-09-30; the withdrawn exception came from `a08cbb6`
- **Deletion test:** a copy or layout change stops breaking tests; behaviour tests and the leak suites keep their proofs
- **Sketch:** sweep `tests/app` and `tests/e2e`: delete copy pins, rewrite the rest to behaviour. Open: how e2e finds elements (roles + names, or stable hooks) — owner decides

## Build & CI

CI runs under 60s; caching that costs nothing is fine, machinery beyond that is not.

### 53. No dependency update policy — Speculative
- **Indicator:** 0 written cadence for Django LTS or the `uv.lock` refresh (2026-10-06); parked on GH #19
- **Evidence:** `pyproject.toml`, `uv.lock`, `docs/django6-notes.md`; a bump moves the Playwright chromium build (`CLAUDE.md`)
- **Sketch:** a rule in `docs/runbook.md`: Django follows its LTS, lock refresh on a fixed rhythm, gate green before merge
