# Test-suite audit 2026-08 — critical core vs. completeness theater

Commissioned by the owner (2026-08-05) after the interview rulings
(`docs/requirements/owner-interview-2026-08.md`): "AI agents have the habit of
creating tests even if they aren't really needed. Which test real critical
stuff, and which are only there for completeness sake?"

**Classification razor (owner, binding):** extensive testing only where a
defect is (a) domain-relevant, (b) data loss, or (c) data leak. Everything
else gets at most light coverage. Applied rulings: the byte-identical-404 law
is relaxed (plain access-denied is fine; *filtering* unauthorized content out
of search/listings stays critical); search needs to work only rudimentarily
for the preview; the color-math namespace is owner-named overkill.

**Method:** every test file read in full (72 files, ~15,400 lines, 1,413
collected tests), production code spot-checked where a verdict depended on it.

## Headline

| | lines | share |
|---|---|---|
| Suite total | ~15,400 | 100% |
| Critical/keep — earns its place under the razor | ~13,400 | ~87% |
| Whole-file deletions | ~820 | ~5% |
| Named slims inside kept files | ~1,190 | ~8% |

The suite's core is genuinely disciplined: real backends instead of mocks
(in-process WebDAV server, fork+SIGKILL crash tests, two-thread CAS races),
and the leak/loss spine is tested at the right layers without redundancy.
The bloat is concentrated at the edges: design-system lints written as
tests, byte-identity machinery for the now-relaxed 404 law, markup/CSS
minutiae, dataclass-mechanics tests, and the same fact re-proven in up to
four files.

## The critical core (keep untouched — this is the map for new devs)

- **Domain access** — `tests/domain/test_access.py`, `test_audience.py`,
  `test_collections.py`, `test_models.py`: the visibility rules themselves.
  Every case is a distinct policy cell; the drift guards catch the
  "field added to floor set but not to projection" leak class.
- **Canonical-store codecs & repositories** —
  `tests/persistence/test_readme.py`, `test_collection_readme.py`,
  `test_article_repository.py`, `test_collection_repository.py`,
  `test_objectstore_conformance.py`, `test_localfs.py`: files are the
  archive; corrupt-decode tables, CAS races (real threads), write-once
  media, recoverable delete, and the fork+SIGKILL atomicity proof are
  direct data-loss prevention. The invalid-key matrix is path-traversal
  safety. Both repos share one `WRITER_LOCK`, but each repo's race test
  proves its own save path holds it — both stay.
- **Index leak suites** — `tests/index/test_leaks.py`,
  `test_leaks_dateless.py`, `test_leaks_decades.py`, `test_equivalence.py`,
  `fixtures.py` (~1,470 lines): named leak channels (text vectors, captions,
  facet values/counts, dateless counts) plus the single proof that the flat
  SQL scope clause cannot drift from `domain.access.can_view` (the
  archetypal leak class of a materialized-scope design). Exactly what the
  owner ruled stays critical.
- **Service layer** — `tests/app/test_services.py`: the adversarial
  staleness gates (unpublish/narrow must be reflected in the very next
  search) and canonical-write-survives-index-failure. The leak and loss
  spine of the whole search surface.
- **Mirror** — `tests/app/test_mirror.py`, `tests/persistence/test_mirror_webdav.py`:
  reconcile deletes from the mirror; the mass-delete-warning test guards
  the one scenario where the system sweeps a human's WebDAV folder.
- **Web trust boundary & media gate** — `tests/app/web/test_viewer_of.py`
  (cookie→Viewer, fail-closed on every tamper branch),
  `test_media.py` (tier×viewer grid on originals+thumbs, authz before
  existence, X-Accel, CRLF header injection), `test_detail_resolver.py`
  (projection flooring), `test_stub_routes.py`.
- **Editing = writing canonical files** — `test_catalog_edit.py` (CAS
  conflict panel, value preservation), `test_catalog_actions.py` (delete/
  publish gates, deny-changes-nothing), `test_catalog_medien.py` (order =
  meaning, caption survival), `test_catalog_form.py`, the whole
  `test_bulk*` quartet (allowlist as privilege boundary, all-or-nothing
  buckets, TOCTOU re-check — a bug corrupts N articles at once).
- **Leak matrix, slimmed** — `test_leak_matrix.py`'s exhaustiveness gate
  (a new route cannot ship without declaring who reaches it) and the
  route×tier deny statuses stay; see slims below for what goes.
- **E2E journeys** (`tests/e2e/`, deselected from the default gate): each
  journey walks a loss/leak spine or pins a named regression (GH#16,
  GH#22, the click-intercepting banner). Gallery tooling stays with the
  design-gate process.

## Whole-file deletions (~820 lines)

| File | Lines | Why |
|---|---|---|
| `tests/app/web/color_math.py` | 129 | Owner-named overkill. Test-only OKLCH→sRGB/WCAG engine; zero production imports (grep-verified). |
| `tests/app/web/test_design_tokens.py` | 130 | Its sole consumer: ~120 parametrized contrast assertions re-parsing a static CSS file; two tests test the test-helper's own parser. |
| `tests/app/web/test_components.py` | 193 | Dev-only component page + raw-color style lint written as a test; prod-unreachability already pinned generically in `test_dev_switcher.py`. |
| `tests/app/web/test_layouts.py` | 130 | Dev-only layout demos + CSS-text assertions; real behavior covered by e2e journeys. Imports `_RAW_COLOR` from test_components — delete together. |
| `tests/index/test_architecture.py` | 146 | AST import-direction police + pinned `__all__`: style enforcement, not behavior; no loss/leak defect reachable through what it catches. |
| `tests/index/test_connectivity.py` | 17 | Pre-Task-5 scaffolding; every django_db test fails more informatively if PG is down. Drop the `pg_connection` fixture with it (rebase test_fts_german's cursor on `db`). |
| `tests/domain/test_viewer.py` | 46 | Re-proves `@dataclass(frozen=True)` and `isinstance` over a module with zero logic; Viewer dispatch is exercised hundreds of times in test_access. |
| `tests/domain/test_errors.py` | 26 | Re-proves Python's exception machinery; the one boundary assert belongs to type-checking, not runtime tests. |

## Named slims (~1,190 lines across kept files)

**Byte-identity relics of the relaxed 404 law** (~150 lines across files):
`_404_shape`/`_media_404_shape` helpers and `byte-identical` asserts in
test_leak_matrix (the `_VOLATILE`/`_shape` machinery), test_catalog_medien,
test_catalog_edit, test_catalog_actions, test_catalog_htmx,
test_catalog_create, test_bulk_views, test_workbench (pane byte-identity),
test_media (five-reasons byte comparison), test_stub_routes, test_detail,
test_collection_edit. In every case: **keep** the 404-status and the
nothing-written/content-absent asserts; **drop** only the byte-for-byte
comparison. Update docstrings that still cite the law.

**test_leak_matrix.py**: collapse the 10 static-asset routes × 5 tiers × 2
methods (100 cases proving CSS returns 200 for everyone) to one case per
route, keeping the routes in `_CONTRACT` so the exhaustiveness gate still
covers them. Content routes keep all tiers — each tier is a distinct leak
cell. (~50 source lines, ~190 executed cases.)

**test_workbench.py** (~210): cut the chrome tail — htmx-attribute and
static-asset wiring tests, CSS-class/glyph/em-dash assertions, sort-header
cycling, the two `load_all` load-count performance pins, and 2 of 3
template-comment viewers. Keep the entire scoping/floored-field/deny spine.

**tests/index/test_search.py** (~145): cut 13 tests that duplicate
test_leaks (floored-field isolation, orphan filter, facet scoping, SearchHit
floor), re-prove collation already pinned elsewhere, assert 0==0 on an
all-dated corpus, or test dataclass machinery.

**tests/index/test_schema.py** (~70): keep the two tsvector-populate tests;
cut objects-exist (subsumed), DDL-generated detail, the third copy of
B1<B2<B10, empty-text default, and the verbatim duplicate of test_indexer's
floor-drift guard.

**tests/index/test_fts_german.py** (~45): keep a slimmed ADR-0011 behavior
lock (the no-compound-decomposition *negative* exists nowhere else); trim
each parametrized table to 2 rows — beyond that it re-proves Postgres'
german_stem/unaccent.

**tests/index/test_indexer.py** (~50): cut the `bool(q)`-only viewer-scope
tests (test_equivalence proves this for real), `_scope_columns` duplicates
of the build_row tier tests, and the frozen-dataclass check.

**tests/app/web/test_catalog_medien.py** (~90): cut the read-count
performance pin and two markup tests; everything guarding order/captions/
deny-unchanged stays.

**tests/app/web/test_catalog_edit.py** (~80): cut the index-lag load-count
pin (user-visible half already in test_catalog_htmx) and the autofocus
markup test; all CAS/value-preservation tests stay.

**tests/app/web/test_catalog_htmx.py** (~55): cut the htmx-attribute
snapshot test and asset-served test; keep partial deny-gating, EDTF echo,
HX-Redirect/302 pair, state-H hinweis.

**tests/app/web/test_catalog_actions.py** (~45): cut 3 of 4 duplicate
template-comment tests and byte-identity lines; delete/publish/CAS spine
stays.

**Smaller**: test_catalog_create asset/markup lines (~25);
test_bulk_views byte-identity helper (~18); test_detail's layout-state
block — Blatt-wording, grid-collapse classes (~75 incl. corpus pruning);
test_tasks' two client-close tests + settings-plumbing isinstance (~59);
test_vocab's three tautological accessor tests (~28);
test_collection_entrypoints' three empty-state copy tests (~30);
test_dev_switcher's favicon pair + merged round-trips (~40);
test_edtf's dataclass/duplicate-branch rows (~40); test_identity's
kwarg-pass-through pair (~17); test_leaks' restated-API test (~10);
test_incremental's duplicate idempotence test (~10).

## Deletion ripples

- `test_layouts.py` imports `_RAW_COLOR` from `test_components.py` — the
  four design files go in one commit.
- Stale references to the deleted files/sweeps: `docs/design/design-system.md`,
  `.interface-design/system.md`, header comments in `tokens.css`,
  `forms.css`, `detail.css`.
- `tests/index/conftest.py` loses the `pg_connection` fixture;
  `test_fts_german.py`'s cursor fixture must rebase onto `db`.
- ADR wording follow-ups already tracked in the interview doc (relaxed 404).

## Recurring patterns (for future writer waves)

1. **Same fact, four files** — the `de_numeric` collation (B1<B2<B10) was
   pinned in test_search, test_schema, test_fts_german, and again per-series.
   One proof per fact, at the layer closest to the user.
2. **Dataclass-mechanics tests** — frozen/equality/isinstance asserts on
   `@dataclass(frozen=True)` re-prove the language.
3. **Performance micro-pins** — load-count spies (`load_all` called once)
   pin implementation, not behavior; they broke no-defect refactors.
4. **Markup/CSS assertions** — class names, glyphs, htmx attributes, copy
   strings: they break on every template tweak and guard none of the razor's
   three categories. The design gate (gallery + e2e) is the right instrument.
5. **Style lints as tests** — raw-color sweeps, import-direction AST walks:
   linter/type-checker territory, not pytest.

Verbatim German error strings in form tests are **not** in category 4 — the
strings are the user contract (test_catalog_form keeps them deliberately).
