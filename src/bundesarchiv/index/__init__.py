"""Derived Postgres search index — the ONLY place Django lives (see ADR 0004, 0005).

This package is an adapter: it materializes the pure domain/persistence core into a
disposable Postgres index with German full-text search, then serves viewer-scoped
queries over it. The public interface is deliberately tiny:

- ``indexer.rebuild(store)`` — wipe and rebuild the index from README files.
- ``query.search(viewer, ...)`` — viewer-scoped, field-floor-aware query.
- ``query.SearchPage`` / ``SearchHit`` / ``SearchFilters`` — the frozen result/query types.

This ``__init__`` imports nothing: both submodules pull in the ``ArticleIndex`` ORM model,
which cannot load before Django's app registry is ready.

Nothing outside ``app`` may import ``bundesarchiv.index`` and nothing inside
``domain``/``persistence`` may import Django (layering convention, enforced in review).
"""
