# Materialized audience scope: index the effective audience, filter it in SQL

Status: Accepted (2026-07-04). Amended by 0014 (2026-07-04): staleness.

The search index stores each Article's **effective audience as flat columns** at index time —
`archivist_only`, `tier`, `groups` — and search filters those columns with a **single SQL
predicate** built from the viewer. Both sides live in one module, `index/scope.py`:
`_scope_columns` on the write side, `_viewer_scope` on the read side. The read predicate is a
**restatement** of `domain.access.can_view`, not a second implementation of it, and their
row-for-row agreement is pinned by a comparison test.

## Considered options

- **Filter live in Python per Article** — run `can_view` over every candidate row after the
  query. Rejected: it cannot use SQL to narrow the result set, so it does not scale, and it
  drags the whole domain into the hot serving path. The index exists precisely to answer
  "which rows may this viewer see" in the database.
- **Cascade the tree in SQL** — store parent links and resolve the nearest-explicit-audience
  walk with a recursive query at search time. Rejected: it reimplements the effective-audience
  logic (Lifecycle gate, widen-not-only-narrow, root default) in SQL, which is the top leak
  risk ADR 0001 exists to prevent. Two implementations drift; one is law.
- **Materialize the resolved audience as columns** (chosen) — resolve once, at index time,
  through the one domain function, and store the flat result. Search then filters flat columns
  with a predicate that mirrors — does not re-derive — the same rule.

## Consequences

- **Comparison, not reimplementation.** `_viewer_scope` and `_scope_columns` sit adjacent and
  mirror each other; no tier comparison exists anywhere else in the index adapter. A
  comparison test (Task 9's `test_equivalence.py`) asserts the SQL predicate selects exactly
  the rows `can_view` would allow, per viewer tier — the read side stays honest to the domain.
- **Writes reindex the subtree synchronously** ([ADR 0014](0014-incremental-reindex.md)).
- **Fail closed on resolution error.** An Article whose chain or audience cannot be resolved is
  still indexed, but as archivist-only (`archivist_only=True`, no tier, no groups) with its
  text intact, so an Archivist can find and fix it. It is never dropped and its visibility is
  never guessed.

**Amended 2026-08:** byte-for-byte deny comparison is no longer a contract, only that a deny
reveals and changes nothing (see the amendment in ADR 0001). The scope filter keeping
unauthorized rows out of results, listings and facet counts stays binding.
