# index — package map

Law: the index is derived and disposable — the README is canonical, `rebuild()` recreates everything
(ADR 0003). Audience scope is materialized into columns at build time (ADR 0012); the scope seam's
row/predicate equivalence against `can_view` is pinned by `tests/index/test_equivalence.py` — never
add a visibility decision that bypasses it. German FTS config per ADR 0011.

- `indexer.py` — materializes canonical files into index rows: full rebuild + incremental (ADR 0014) · interface: `rebuild`, `index_article`, `index_subtree`, `build_row`, `file_kind`, `mime_type` · tests: `tests/index/`
- `query.py` — viewer-scoped search over the derived index (ADR 0003/0004) · interface: `search`, `SearchPage`, `SearchFilters`, `SearchHit` · tests: `tests/index/test_search.py`, `test_leaks*.py`, `test_fts_german.py`
- `scope.py` — the scope seam: viewer visibility → index columns (write side) + SQL predicate (read side), both unions closed by `assert_never` · interface: `ScopeColumns` · tests: `tests/index/test_equivalence.py`
- `models.py` — the derived, private Postgres row · interface: `ArticleIndex` · tests: `tests/index/test_schema.py`

Internal: `settings.py`, `settings_dev.py`, `wsgi.py`
