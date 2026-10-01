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
- **Evidence:** `browse_views.py` slot label from `bestand.names()` (all Collections); `article_auth.py` asserts "names are member-safe" without a ruling. Owner 2026-10-01: OK for now, revisit
- **Deletion test:** n/a — a missing rule, not a module
- **Sketch:** decide with group access / the policy rework; if names are scoped, the slot label comes from the viewer-scoped facet only

### 31. The publish precondition lives in the view, spelled three ways — Worth exploring
- **Indicator:** 3 spellings of "the chain must resolve" (2026-10-01, W4)
- **Evidence:** `catalog_views` edit POST (submitted Bestand), publish route (stored one), status options (`inherited is None`). Bite: `236e525` (published anyway), `b8244dd` (2nd copy).
- **Sketch:** one pure `can_publish(chain)` in the domain; the three callers ask it.

### 32. "Public" and "Archivist" have several definitions — Speculative
- **Indicator:** 3 definitions of Public; 118 tests build `Public()`; the form still offers "Öffentlich" (2026-10-01, A5)
- **Evidence:** `viewer.py:14,30`, `oidc.py:20`, `anonymous_gate.py:56-61`, `vocab.py:141,177`. Archivist is a group in `CONTEXT.md`, a realm role in code.
- **Sketch:** owner 2026-10-01: Public stays for future link access. Docs only: `CONTEXT.md` states both terms as built.

### 33. Medienart / Dokumenttyp: fixed lists in code, free text by ruling — Worth exploring
- **Indicator:** pair rules restated in 8 sites over 3 modules; 2 Dokumenttyp-option routes, 5 param aliases (2026-10-01, P5/W5)
- **Evidence:** `catalog.py:149-160`, `bulk_views.py`, `bulk.py`, `catalog_views.py:995-1009`; `vocab.py` in `app/web` is imported by a command and injected into `legacy.py`. Every pair is valid today, so the refusal branches never run.
- **Deletion test:** free text deletes all 8 pair rules and both routes; `vocab` lists become suggestions. `media_type` still names Medienart and MIME type: rename one.

## Module map & packages

### 11. Cross-module private imports mark undeclared seams — Worth exploring
- **Indicator:** 11 imports of 8 private names: 5 in `persistence/fixity.py`, 5 in `index`, 1 in `app/web`
  (2026-10-01, better; 14 / 10 names on 2026-09-25; same AST count of `from bundesarchiv… import _name`)
- **Evidence:** `media_views._not_found` ×5; `viewers`, `catalog`, `catalog_views`, `browse_views`,
  `index.models` and `index.scope` each hand one or two private names to siblings. Accreted.
- **Sketch:** promote the deny helper to a public web-level name; each other name goes public on its
  module or moves to its one importer.

### 49. The fixity check reads the repositories' private layout — done
- **Indicator:** 5 private imports, all in `persistence/fixity.py` (2026-10-01, stable; the count of #11)
- **Evidence:** `_folder` and `_ulid_of_readme` from both repositories, and `repository._digest` —
  the key layout and the hash the check re-reads (ADR 0019 "Fixity"). Accreted. P2 adds: the
  repositories repeat the key scheme byte-identically (`repository.py:222-244`, `collections.py:103-113`).
- **Sketch:** a named internal layout module beside `_writer` (record folders, README keys, the
  media digest) that both repositories and `fixity` import.
- **Done 2026-10-01:** `persistence/_layout.py` owns record folders, README keys and the media digest; both repositories and `fixity` import it (Wave CLEAN).

### 34. Field labels are declared twice, "Typ" derived three ways — Worth exploring
- **Indicator:** 6 labels in both `card.FIELDS` and `bulk.FIELDS`, a third time in `bulk.apply_field` (2026-10-01, W6)
- **Evidence:** `card.py:138-293`, `bulk.py:61-71,153-168`, `ledger.py:39`, `browse_views.py:264,650`. Bite: `5c902a2`.
- **Sketch:** one label source both registries read; one rule for "Typ".

### 35. The post-write tail is written out six times — Strong
- **Indicator:** 6 copies of mirror enqueue, index sync, reindex fallback in 2 modules (2026-10-01, P3)
- **Evidence:** `articles.py:61-64,145-148,187-189,210-212`, `collections.py:46-47,70-72`. Bite: `bbad5ee`, `d72d266`, `d3c2c12` co-edited both.
- **Sketch:** one `after_write(...)` returning the lag result; see #41.

### 36. Group strings have no owner — Strong
- **Indicator:** exact-equality group match in 3 places; 0 value types (2026-10-01, A1)
- **Evidence:** `access.py:72-75`, `scope.py:74-78`, `query.py:477-483`, `oidc.py:34`. `/Orden St. Georg/Komturei` does not satisfy `/Orden St. Georg` (probe). No group audience in data yet.
- **Sketch:** a `Group` value type: one parse of the claim, one match rule.

### 37. "What a non-Archivist may see" is declared in 7 places — Strong
- **Indicator:** 7 declarations, 3 drift guards, 2 unguarded; 2 contradict on `audience` (2026-10-01, A2)
- **Evidence:** `access.py:24,92`, `indexer.py:91,108-114`, `query.py:180-194`, `index/models.py:40-49`. Bite: `91900b3` (group names leaked), `ed4c054`.
- **Sketch:** one owner of the visible attributes; the Python/SQL scope pair stays two encodings.

### 38. One undecodable README stops every index writer — Strong
- **Indicator:** 0 handlers in `rebuild`/`index_article`/`index_subtree`/`load_all`; 5 policies for one broken file (2026-10-01, P4)
- **Evidence:** `indexer.py:256-260,292,317`, `collections.py:75`, `repository.py:214`; `UnicodeDecodeError` escapes `load`. A visibility narrowing then never reaches the index.
- **Sketch:** ruled policy (owner 2026-10-01): archivist-only, flagged for review. One loader that returns it.

### 39. Mirror push overwrites a remote README without checking its token — Worth exploring
- **Indicator:** 1 unchecked path; only reconcile compares (2026-10-01, P6)
- **Evidence:** `mirror.py:227-235` vs `:151-156`. Bites when the StorageShare is canonical (hand edits).
- **Sketch:** push compares the remote version token first, as reconcile does.

### 40. Persistence trusts a ulid as a key segment — Speculative
- **Indicator:** `is_valid_ulid` checked 6× in web, 0× in persistence and domain (2026-10-01, P8)
- **Evidence:** `repository.py:222`, `collections.py:103`.
- **Sketch:** validate once where a key is built.

## Interfaces

### 41. "Index lagged" has no owner — Strong
- **Indicator:** `index_updated` is a bool on 3 result types; 4 routes drop it (media actions, create, copy, Bestand rename) (2026-10-01, W2)
- **Evidence:** `catalog_views.py:277,615,756,691,942,634`, `catalog.py:347`, `collection_views.py:139-144`. Bite: `ab528a6`. ADR 0014 asks the warning on visibility changes.
- **Sketch:** one lag result the post-write tail (#35) returns and the landing must handle.

### 42. A broken Bestand chain: list shows, detail 404s, edit opens — Worth exploring
- **Indicator:** 1 carve-out breaks "list == detail == reference" (2026-10-01, A7)
- **Evidence:** `access.py:36-43`, `catalog_views.py:76-89`, `test_equivalence.py:24-33` (ADR 0012).
- **Sketch:** ruled 2026-10-01: Archivists see it. Detail, pane and media stop 404ing for them.

### 26. A media route re-derives the version its own save started from — Worth exploring
- **Indicator:** 1 site, `catalog_views._media_surface` (`version == held + 1`) (2026-10-01, stable; bit twice more: `eb71b4c`, `1452c38`)
- **Evidence:** `app/result.py::Updated` carries only the new version; `app/articles.update_article`
- **Deletion test:** with `Updated.base`, the ADR 0013 counter arithmetic leaves the web layer
- **Sketch:** `Updated(article, version, base)`; `_media_surface` advances iff `base == held`

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

### 8. Trefferliste — name the results view-model — in progress (Wave LIST)
- **Indicator:** ~20-key untyped dict; 6 `type: ignore` in `browse_views.py` (2026-09-02). Wave LIST:
  the `type: ignore`s are gone (`page: SearchPage`) and the ledger's rows and columns are typed
  (`ledger.py`); the rest of `_results_context` is still a dict. 0 `type: ignore` (2026-10-01, stable).
- **Evidence:** `_results_context` + seven pure helpers inside the route; `page: object` although
  `SearchPage` is public. ~25 of ~60 workbench tests are pure link-algebra assertions each paying
  Postgres + corpus + rebuild + HTTP + HTML grep.
- **Sketch:** pure `results_view(parsed, page: SearchPage, …) -> Trefferliste` frozen dataclass;
  the security-spine and HTMX render-fork tests stay on the route per the testing razor.

### 9. CollectionTree — deepen the resolver's input — Worth exploring
- **Indicator:** `resolve_chain` called at 5 sites in 4 modules (2026-10-01, better; 6 on 2026-09-01);
  the 2 web `_collections` copies now go through `BestandChooser.chain_of` (Wave CLEAN, 2026-10-01);
  `index/indexer.py:256,292,317` still build the lookup 3×
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
  third time in `copy_article` (2026-10-01, stable). P1 adds: a new text field = ~14 edits in 9 files,
  a faceted one 20 files; the round-trip test fills 10 of 18 fields
- **Evidence:** `app/articles.py` forwards 1:1 to `identity.create_article`. A DTO in all but name —
  ADR 0008 territory.
- **Deletion test:** fails as written (pure forwarding).
- **Sketch:** `create_article(archive, article: Article)`; the view mints the valid-by-construction
  Article, and `copy_article` becomes `replace(source, ulid=new_ulid(), …)`.

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

### 27. The thumbnail root is resolved in five places — Worth exploring
- **Indicator:** 5 `Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)` sites (2026-10-01, stable)
- **Evidence:** `app/tasks.py`, `app/web/media.py`, `import_legacy`, `browse_views`, `rebuild_thumbnails`
- **Deletion test:** one `thumbnails.root()` removes four copies of the settings lookup
- **Sketch:** `thumbnails.root() -> Path`; callers pass nothing

### 28. Thumbnails decode a whole image before downscaling — Speculative
- **Indicator:** up to ~179M px decoded per image (Pillow's bomb limit) (2026-10-01, stable; still no `draft`)
- **Evidence:** `app/thumbnails.py::_picture`; JPEG could decode reduced via `Image.draft`
- **Deletion test:** `draft` cuts worker memory on large scans; no change to the output
- **Sketch:** `image.draft("RGB", (side, side))` before `load()` for JPEG

### 43. Landing state rides in four hand-spelled query params — Strong
- **Indicator:** 4 params, 3 written in one module and read in another (2026-10-01, W3). Raised: the start page comes soon.
- **Evidence:** `collection_views.py:74,186`, `catalog_views.py:151,198,635`, `browse_views.py:582`. `?angelegt=` echoes any text from the URL.
- **Sketch:** one landing vocabulary (encode/decode pair); the delete feedback would be a 5th param.

### 44. "What kind of htmx request" is read raw in 8 places — Strong
- **Indicator:** 8 raw `HX-` reads in 5 modules (2026-10-01, W7). Raised: the start page comes soon.
- **Evidence:** `anonymous_gate.py:48`, `browse_views.py:113,115`, `catalog_views.py:127,710`, `collection_views.py:77,169`, `viewers.py:257`. Bite: `2675e6c`, `33a9d6a` (history restore missed twice).
- **Sketch:** one `request_kind(request)`.

### 45. The two README codecs are drifted copies — Strong
- **Indicator:** 6 parallel definitions in `readme.py` and `collection_readme.py` (2026-10-01, A6/P2)
- **Evidence:** `readme.py:31-153,225-238` vs `collection_readme.py:31-112`. `groups: vorstand` decodes to `('v','o','r',…)` in a Collection, raises in an Article. Bite: `db66d49` fixed one copy; `96e44cf`, `d6c8b22`.
- **Indicator 2026-10-01 (after Wave CLEAN):** the group decoder is shared (scalar `groups` refused in both); `_MARKER`, `_FENCE`, `_parse_front_matter`, `_version_of` still twice.
- **Sketch:** one front-matter module both import.

### 46. `SearchHit.tier` and `.groups` have no reader — done (Wave CLEAN, 2026-10-01)
- **Indicator:** 0 readers in `src/`, 25 test pins (2026-10-01, A3)
- **Evidence:** `query.py:121,131,179,477`. The `91900b3` leak sat in this unread field.
- **Deletion test:** delete both fields and the pins; nothing changes.

### 47. Dead code: `tasks.full_rebuild` and `identity.slugify` — done (Wave CLEAN, 2026-10-01)
- **Indicator:** 2 symbols with no caller in `src/` (2026-10-01, P7); `slugify` has only its own test
- **Evidence:** `tasks.py:14,97-101,116` (two false docstring claims; job `reconcile` collides with `mirror.reconcile`).
- **Deletion test:** both go, with their tests and map rows.

### 48. `changed_by` is spelled several ways — Worth exploring
- **Indicator:** 3 spellings: `hard_delete_article` takes none, `catalog_views.py:663` passes an unused `_by`, `mark_deleted(by=)` vs `save(changed_by=)` (2026-10-01)
- **Evidence:** `articles.py:203`, `repository.py:68`; app law says every write names its author.
- **Indicator 2026-10-01 (after Wave CLEAN):** 1 left, the unused `_by` at `catalog_views.py:663`; `mark_deleted` takes `changed_by`; app law now says every write that writes a version names its author.
- **Sketch:** one keyword, `changed_by`, on every write.

### 19. Compositions style inside components — done
- **Indicator:** 0 composition reach-ins, the lint's allow-list deleted (2026-09-26; 44 → 37 → 1 → 0
  over WAVE-C); 0 wrapper-sensitive knob sites (Wave R U1 cut the record card's `.fach > .field`; the
  form-sheet sets `--field-font` on its own root)
- **Deletion test:** pages set knobs only; a wrapper or a new field changes no composition CSS

### 14. `catalog_views.py` is the wave's dumping ground — Strong (pointer entry)
- **Indicator:** 1009 lines, 12 routes (2026-10-01, better; 1380 on 2026-09-02, ~970 before the
  registry landed)
- **Evidence:** routes, the field registry, the structural-save retry, the media drawer and the
  Bestand chooser all live here. Accreted.
- **Sketch:** no separate fix — #3 (EditSurface), #4 (CAS lift) and #7 (BestandChooser) each carve
  out a piece. Re-measure the line count after each.

### 15. Archivist route gate spelled many ways — Speculative
- **Indicator:** 15 hand-written `request.method != …` re-checks in `app/web` (2026-10-01, worse; 8 on
  2026-09-02); 13 `isinstance(…, Archivist)` sites in 9 modules (A8: the policy rework's real cost)
- **Evidence:** `_load_gated` omits method checking, so callers re-append it. Related: `viewer_of`
  resolves up to 4× per request.
- **Cost class:** tidiness, not safety — `test_leak_matrix._CONTRACT` exhaustiveness already makes a
  forgotten gate loud.
- **Sketch:** an `@archivist_route(method=…, needs_article=True)` decorator seam.

### 16. Shallow wrappers that fail the deletion test — Speculative
- **Indicator:** 3 pass-throughs (2026-10-01, worse; 2 on 2026-09-02, of which only `card._audience_label` is left)
- **Evidence:** `card._audience_label`, `app/reindex.py` (3 lines, 1 caller). `article_auth.resolve_visible_article`
  inlined (Wave CLEAN, 2026-10-01): 2 left.
- **Deletion test:** fails — inlining each removes a name and adds nothing.

### 20. Variants in disguise (law C2) — Strong
- **Indicator:** 3 open in the monochrome mock system, 5 in the app (2026-10-01, stable; no CSS change
  to the listed items since 2026-09-27).
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

### 24. Web view modules import each other in a cycle — done
- **Indicator:** 1 function-local import (`viewers.render_screen` → the header panel builders),
  2026-09-30 → 0 (2026-09-30).
- **The pattern:** `catalog_views` imports `browse_views` and `collection_views` imports
  `catalog_views`, so a module both of them reach (`viewers`) cannot import the panel builders
  at module level. Wave REST U2 worked around it with one local import.
- **Evidence:** `app/web/card.py` (the field registry, `CardRow`) and `app/web/panels.py`
  (`FormPanel`, `header_panels`) import no view module. The registry moved too: the "Neuer Artikel"
  panel's rows come from it.

## Tests

### 29. The gallery has no lead without a picture — Worth exploring
- **Indicator:** 0 gallery states render `.platte:has(.blank)` (2026-10-01, stable)
- **Evidence:** every e2e corpus file now has a thumbnail (PDFTHUMBS); `static/detail.css`
- **Deletion test:** a non-renderable corpus file (audio/video) brings the state back
- **Sketch:** one audio file on a corpus article + a `detail-audio` gallery state

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

### 25. The gallery is one test — Weak — done 2026-10-01
- **Indicator:** 1 test renders every state, 2026-09-30.
- **The pattern:** the first `_reach_*` exception aborts every render after it, so each red costs a
  full ~2 min re-run (Wave REST U4 paid it twice).
- **Sketch:** parametrize the gallery over its states, or collect reach failures and fail at the
  end with all of them.
- **Closed 2026-10-01:** one test per state (`-k <state>` renders one; a bad reach fails alone) and
  `mise run test:gallery-diff` (a ref vs the tree, per-PNG verdict).
- **Still open:** `mise run mutate` runs plain pytest, so it cannot prove an e2e pin (a `menu.js` mutation was done by hand).

## Process law

- **Row budget friction** — `ROW_MAX_CHARS=220` forced 4 rewrites of one interface-rich row (bestand.py, 2026-09-03, landed at exactly 220). One occurrence = instance, not evidence; if a second row fights the cap, investigate the budget (wrap the interface segment vs raise) per the framework-health rule. Indicator: rows within 10 chars of cap: 19 (2026-10-01, worse; 1 on 2026-09-03). Map rows are stale at every audit (review pattern 7): a framework-health trigger; owner 2026-10-01 chose a gate (every listed interface name exists, `5080d85`) over changing the rule.

- **The second caller copies a decision instead of moving it** — 10 findings in the 2026-10-01 review (#9, #49, #31, #33–37, #43–44). Adopted: writer-brief "One owner per decision" (`e488814`); gated where mechanical by `tests/test_structure.py`. Indicator: 10 copies found (2026-10-01).

- **Left (2026-10-01):** each state rebuilds the corpus (`live_server` → `transactional_db` truncates the index), so the full run is ~9% slower (135 s) and `test:gallery-diff` takes ~4.5 min; a module-scoped corpus would cut both but changes the isolation `edit-conflict` relies on. The diff task's first version compared only the alpha band (always "identical"); fixed 2026-10-01 (RGB). A re-check of the rebuild (`f45b8db` vs `91a500b`) then showed 35 changed PNGs, all from the old single-test run leaking a bulk edit's author ("Sammel-Autor") into later states; per-state isolation removed that leak, so the new renders are the correct ones.
### 23. Tests pin UI copy and markup — Strong
- **Indicator:** 109 `"…" in body`-style asserts in `tests/app`, 201 `get_by_*`/`locator(` calls in `tests/e2e` (2026-10-01; new grep, not comparable with 188 / 53 of 2026-09-30 — baseline reset)
- **Evidence:** owner ruling 2026-09-30 (`owner-interview-2026-08.md`, "Ruling of 2026-09-30 (tests)"); the withdrawn exception came from `a08cbb6`
- **Deletion test:** a copy or layout change stops breaking tests; behaviour tests and the leak suites keep their proofs
- **Sketch:** sweep `tests/app` and `tests/e2e`: delete copy pins, rewrite the rest to behaviour. Open: how e2e finds elements (roles + names, or stable hooks) — owner decides

## Build & CI

CI runs under 60s with no caching machinery (owner ruling); keep it that way.

### 22. Parallel worktrees share one test database — done
- **Indicator:** 1 collision (2026-09-28): a gate in one worktree failed 1743 setups with
  `DROP DATABASE "test_bundesarchiv"` refused while another worktree's gate held the database.
  0 (2026-09-30): two worktrees ran `mise run test:db` at once, both green.
- **Cause:** every worktree's Postgres-backed suite used the same test database name.
- **Fix:** `tests/conftest.py` suffixes the test database with the checkout's directory name.
