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
  linter/type-checker territory.
- **Performance micro-pins** (load-count spies) — they pin implementation, not
  behavior.
- **Byte-identical response comparisons** — the byte-identical-404 law was
  relaxed (2026-08); see the deny contract below.
- **Markup minutiae** (CSS classes, glyphs, htmx attributes, copy strings) —
  the design gate (gallery + e2e) is the instrument for that. Exception:
  verbatim German UI/error strings ARE the user contract — assert those.
- **A second proof of a fact already pinned elsewhere.** One proof per fact, at
  the layer closest to the user (the `de_numeric` collation was once pinned in
  four files).

## The deny contract

A deny/absence/malformed-param on a prod route is `assert_denied` from
`tests/app/web/_asserts.py` (status 404 + empty body), plus a
nothing-was-written assert on write routes. Every new prod route needs a
`_CONTRACT` entry in `tests/app/web/test_leak_matrix.py` — the exhaustiveness
gate fails otherwise.

## What each suite owns

- `domain/` — the visibility policy itself (access, audience resolution,
  fail-closed chains) and value-object invariants. Leak-critical.
- `persistence/` — canonical files: codecs (corrupt-decode tables), CAS races,
  crash durability, the ObjectStore contract across all three adapters.
  Loss-critical.
- `index/` — viewer-scoped search: the leak suites (`test_leaks*.py`), the
  SQL-vs-domain equivalence proof (`test_equivalence.py`), indexer/incremental
  correctness. Leak-critical; the index itself is disposable.
- `app/` — the service layer (staleness gates, canonical-write-survives-index-
  failure), mirror reconcile (mass-delete warning), worker jobs.
- `app/web/` — HTTP gates (leak matrix, media serving, viewer_of) and the
  editing surface (CAS conflicts, bulk buckets, media order). Editing writes
  canonical files — deny-changes-nothing asserts are load-bearing.
- `e2e/` — real-browser journeys + the state gallery (both deselected from the
  default run); each journey walks a loss/leak spine or pins a named regression.
