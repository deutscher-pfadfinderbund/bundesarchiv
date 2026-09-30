# Test-suite law

## The testing razor (owner ruling, 2026-08)

Extensive coverage ONLY where a defect is (a) domain-relevant, (b) data loss, or
(c) data leak. Everything else gets light coverage or none. Source:
`docs/requirements/owner-interview-2026-08.md`; the full audit that applied it is
in git history (`docs/plans/test-audit-2026-08.md`, removed after execution).

## Do not write

- **Dataclass/framework/library-mechanics tests** (frozen raises, equality of
  equal values, `isinstance`, re-proving Postgres stemming beyond one lock case).
- **Style lints as tests** (color sweeps, import-direction AST police) — that is
  linter/type-checker territory. ONE deliberate exception by owner ruling
  (design-review-law section E): `app/web/test_design_lint.py` enforces the
  law's lintable subset over the prod stylesheets.
- **Performance micro-pins** (load-count spies) — they pin implementation, not
  behavior.
- **Byte-identical response comparisons** — the byte-identical-404 law was
  relaxed (2026-08); see the deny contract below.
- **UI copy and markup** (German strings, CSS classes, glyphs, htmx attributes,
  element structure) — owner ruling 2026-09-30. Tests assert behaviour: which
  records a viewer gets, where a link or form goes and with which state, what is
  written, what is denied, which data values reach the page. Copy and look are
  the owner's to judge on the gallery and the live pages. A test that fails only
  because copy or markup changed is deleted or rewritten to the behaviour under
  it, never updated to the new string. Exception: a derivation gate that parses a
  rendered attribute back out to compare against its source of truth (e.g.
  `data-bulk-wert` vs `bulk.FIELDS`) asserts derived values, not markup.
- **Hand-rolled DB gating** (a connection probe, a `skipif`, a manual
  `requires_pg`) — `tests/conftest.py` derives the marker from each test's
  fixture closure. Mark by hand only for DB use that closure cannot see.
- **A second proof of a fact already pinned elsewhere.** One proof per fact, at
  the layer closest to the user (the `de_numeric` collation was once pinned in
  four files).

## Strict templates

Under every suite a missing `{{ var }}` raises, naming the variable (`tests/conftest.py`), and so
does a filter on it, `|default` included. A value that is optional by design uses
`{% firstof var %}` or `{% if var %}`; everything else is passed explicitly.

## The deny contract

A deny/absence/malformed-param on a prod route is `assert_denied` from
`tests/app/web/_asserts.py` (status 404 + empty body), plus a
nothing-was-written assert on write routes. Every new prod route needs a
`_CONTRACT` entry in `tests/app/web/test_leak_matrix.py` — the exhaustiveness
gate fails otherwise.

## The round-trip contract

Every encode/decode or serialize/parse pair carries an adversarial round-trip
test in the commit that introduces it — the delimiter itself, empty, unicode,
percent, leading/trailing whitespace. Canonical bytes are the archive, so this
sits inside the razor as loss-critical, not as codec-mechanics.

## What each suite owns

- `domain/` — the visibility policy itself (access, audience resolution,
  fail-closed chains) and value-object invariants. Leak-critical.
- `persistence/` — canonical files: codecs (corrupt-decode tables), CAS races,
  crash durability, the ObjectStore contract across all three adapters.
  Loss-critical. Collected counts here move in multiples: the `repo` fixture
  is adapter-parametrized, so one test function is two collected tests (the
  conformance suite: three).
- `index/` — viewer-scoped search: the leak suites (`test_leaks*.py`), the
  SQL-vs-domain equivalence proof (`test_equivalence.py`), indexer/incremental
  correctness. Leak-critical; the index itself is disposable.
- `app/` — the service layer (staleness gates, canonical-write-survives-index-
  failure), the push to the system of record (push order, never an unchanged file
  twice, the add-only reconcile), worker jobs.
- `app/web/` — HTTP gates (leak matrix, media serving, viewer_of) and the
  editing surface (CAS conflicts, bulk buckets, media order). Editing writes
  canonical files — deny-changes-nothing asserts are load-bearing.
  `/static/*` is served by WhiteNoise, not the urlconf, so the leak matrix
  cannot see it: its public-by-design contract lives in `test_static_assets.py`
  (asset whitelist, unhashed and uncollected paths not served).
  Build the archive with the `corpus` / `make_corpus` fixtures and the
  `client_as` / `make_*` helpers from `app/web/_fixtures.py` — one `client_as`
  signs every viewer, and no module keeps a local `_Corpus` / `_client_as` /
  `_settings` to clone. Reach for the standard `corpus` and the `make_*`
  builders first; wire something bespoke only when the standard shape genuinely
  does not fit. That shape is frozen — a test asserting a global count or
  listing builds its own content with `make_corpus`.
  Articles for any suite come from `tests/_articles.py::make_article` (PUBLISHED by default);
  the web suite's `make_article` is that builder with the public Bestand filled in.
- `e2e/` — real-browser journeys + the state gallery (both deselected from the
  default run); each journey walks a loss/leak spine or pins a named regression.
  `test_a11y.py` is the axe-core WCAG 2.2 AA pass over the journey pages
  (color-contrast disabled per the 2026-08 audit ruling; axe vendored under
  `e2e/vendor/`).
  **`e2e/_pages.py` is THE screen inventory**: every GET-reachable screen, once,
  with its viewer tier, the minimum overlay panels it composes and the control
  rows it must show. The axe pass, both control-row walks, the overlay
  containment walk and the gallery's GET states all derive from it — a new screen
  joins that tuple and is covered everywhere the same day (G.21 applied to page
  coverage). Never re-type a page list in a test; add the screen.
  Some invariants are deliberately proven TWICE, at two layers — the server's
  decision in the fast suite, the browser's answer in `e2e/` (the folded-section
  rule is the canonical pair). That is layering, not duplication; the comment at
  each site says so.

The header's tool panels list every Bestand on every archivist page. A test asserting that a
value reaches a page scopes itself to the region under test (`<main`), or it passes vacuously.
