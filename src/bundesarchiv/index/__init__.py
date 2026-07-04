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

from typing import TYPE_CHECKING

from bundesarchiv.persistence.objectstore import ObjectStore

if TYPE_CHECKING:
    from bundesarchiv.index.indexer import RebuildReport

# Order is the fixed public contract (Task 4 brief); the architecture test pins this exact
# sequence. Do not let isort/RUF022 resort it.
__all__ = ["rebuild", "search", "SearchPage", "SearchHit", "SearchFilters"]  # noqa: RUF022


def rebuild(store: ObjectStore) -> RebuildReport:
    """Wipe and rebuild the derived index from the README files on `store` (Task 7).

    A thin re-export: the implementation lives in ``bundesarchiv.index.indexer``, imported
    lazily here because that module pulls in the ``ArticleIndex`` ORM model, which cannot be
    imported at package-init time (before Django's app registry is ready).
    """
    from bundesarchiv.index.indexer import rebuild as _rebuild

    return _rebuild(store)


def search() -> None:
    """Viewer-scoped, field-floor-aware search. Implemented in Task 8."""
    raise NotImplementedError("search() lands in Task 8")


class SearchPage:
    """A page of search results with facet counts. Defined in Task 8."""


class SearchHit:
    """A single floor-safe search result row. Defined in Task 8."""


class SearchFilters:
    """Facet/filter selection for a search query. Defined in Task 8."""
