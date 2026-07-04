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

from typing import TYPE_CHECKING, Any

from bundesarchiv.persistence.objectstore import ObjectStore

if TYPE_CHECKING:
    from bundesarchiv.index.indexer import RebuildReport
    from bundesarchiv.index.query import (
        SearchFilters as SearchFilters,
    )
    from bundesarchiv.index.query import (
        SearchHit as SearchHit,
    )
    from bundesarchiv.index.query import (
        SearchPage as SearchPage,
    )
    from bundesarchiv.index.query import (
        search as search,
    )

# Order is the fixed public contract (Task 4 brief); the architecture test pins this exact
# sequence. Do not let isort/RUF022 resort it.
__all__ = ["rebuild", "search", "SearchPage", "SearchHit", "SearchFilters"]  # noqa: RUF022

# The public names ``search`` / ``SearchPage`` / ``SearchHit`` / ``SearchFilters`` live in
# ``bundesarchiv.index.query``, which pulls in the ``ArticleIndex`` ORM model — that can't be
# imported at package-init time (before Django's app registry is ready). So they are resolved
# lazily via ``__getattr__`` (PEP 562): the first attribute access imports ``query`` and caches
# the object on the module. ``rebuild`` follows the same lazy pattern (its own thin wrapper).
_LAZY = frozenset({"search", "SearchPage", "SearchHit", "SearchFilters"})


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from bundesarchiv.index import query

        value = getattr(query, name)
        globals()[name] = value  # cache so subsequent lookups skip __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def rebuild(store: ObjectStore) -> RebuildReport:
    """Wipe and rebuild the derived index from the README files on `store` (Task 7).

    A thin re-export: the implementation lives in ``bundesarchiv.index.indexer``, imported
    lazily here because that module pulls in the ``ArticleIndex`` ORM model, which cannot be
    imported at package-init time (before Django's app registry is ready).
    """
    from bundesarchiv.index.indexer import rebuild as _rebuild

    return _rebuild(store)
