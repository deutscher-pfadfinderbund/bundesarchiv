"""Derived Postgres search index — the ONLY place Django lives (see ADR 0004, 0005).

This package is an adapter: it materializes the pure domain/persistence core into a
disposable Postgres index with German full-text search, then serves viewer-scoped
queries over it. The public interface is deliberately tiny:

- ``rebuild(store)`` — wipe and rebuild the index from README files (Task 7).
- ``search(viewer, ...)`` — viewer-scoped, field-floor-aware query (Task 8).
- ``SearchPage`` / ``SearchHit`` / ``SearchFilters`` — the frozen result/query types.

Nothing outside this package may import ``bundesarchiv.index`` and nothing inside
``domain``/``persistence`` may import Django (tests/index/test_architecture.py pins both).

The names below are stubs; Tasks 6-8 fill them in. They exist now so the public
interface is fixed and the architecture test can assert ``__all__``.
"""

# Order is the fixed public contract (Task 4 brief); the architecture test pins this exact
# sequence. Do not let isort/RUF022 resort it.
__all__ = ["rebuild", "search", "SearchPage", "SearchHit", "SearchFilters"]  # noqa: RUF022


def rebuild() -> None:
    """Wipe and rebuild the index from README files. Implemented in Task 7."""
    raise NotImplementedError("rebuild() lands in Task 7")


def search() -> None:
    """Viewer-scoped, field-floor-aware search. Implemented in Task 8."""
    raise NotImplementedError("search() lands in Task 8")


class SearchPage:
    """A page of search results with facet counts. Defined in Task 8."""


class SearchHit:
    """A single floor-safe search result row. Defined in Task 8."""


class SearchFilters:
    """Facet/filter selection for a search query. Defined in Task 8."""
