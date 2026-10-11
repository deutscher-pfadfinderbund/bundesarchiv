# index — package map

Law: the index is derived and disposable — the README is canonical, `rebuild()` recreates
`ArticleIndex` (ADR 0003); `MediaText` is derived from the files, kept across rebuilds, pruned by
rebuild to the hashes some row names, and refilled by `app.media_text` (ADR 0023). Audience scope
is materialized into columns at build time (ADR 0012); the scope seam's row/predicate equivalence
against `can_view` is pinned by `tests/index/test_equivalence.py` — never add a visibility decision
that bypasses it. German FTS config per ADR 0011.

- `indexer.py` — materializes canonical files into index rows: full rebuild + incremental (ADR 0014) · interface: `rebuild`, `index_article`, `store_media_text`, `hashes_with_text`, `file_kind` · tests: `tests/index/`
- `query.py` — viewer-scoped search and counts (ADR 0003/0004) · interface: `search`, `facet_counts`, `SearchPage`, `SearchFilters`, `SearchHit`, `suggest_tags` · tests: `test_search.py`, `test_leaks*.py`, `test_tag*.py`
- `scope.py` — the scope seam: viewer visibility → index columns (write side) + SQL predicate (read side), both unions closed by `assert_never` · interface: `ScopeColumns` · tests: `tests/index/test_equivalence.py`
- `models.py` — the derived, private Postgres rows: one per Article, one per PDF page · interface: `ArticleIndex`, `MediaText` · tests: `tests/index/test_schema.py`, `test_media_text.py`

Internal: `settings.py`, `settings_dev.py`, `wsgi.py`
