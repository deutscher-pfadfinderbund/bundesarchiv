# index — package law

Law: the index is derived and disposable — the README is canonical, `rebuild()` recreates
`ArticleIndex` (ADR 0003); `MediaText` is derived from the files, kept across rebuilds, pruned by
rebuild to the hashes some row names, and refilled by `app.media_text` (ADR 0023). Audience scope
is materialized into columns at build time (ADR 0012); the scope seam's row/predicate equivalence
against `can_view` is pinned by `tests/index/test_equivalence.py` — never add a visibility decision
that bypasses it. German FTS config per ADR 0011.
