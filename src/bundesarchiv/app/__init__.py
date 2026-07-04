"""The application-service layer — the imperative shell the Part 4.5+ views call (ADR 0014).

This is the ONLY package allowed to import ``bundesarchiv.index`` (the architecture test pins it):
it wires the pure domain + persistence core to the derived Postgres index. Each service is a thin,
explicit two-step — the canonical repo write (CAS, ADR 0013) THEN the synchronous index update
(ADR 0014) — and returns a ``SaveResult`` whose ``index_updated`` flag lets the view show the
ADR-mandated specific warning when the index update failed but the canonical write stood.

It IS an installed Django app (so Procrastinate autodiscovers ``tasks.py`` and Django discovers the
``ensure_index_current`` management command), but its public names are resolved LAZILY (PEP 562,
same pattern as ``bundesarchiv.index``): the services transitively import the ``ArticleIndex`` ORM
model, which cannot be imported at app-``populate()`` time before the registry is ready. Importing
them on first attribute access — always after ``ready()`` — keeps the package init cheap and safe.

Kept deliberately small (YAGNI): only the write paths Parts 4.5-4.8 will demonstrably use —
save/create/delete Article, save Collection.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bundesarchiv.app.articles import (
        create_article as create_article,
    )
    from bundesarchiv.app.articles import (
        hard_delete_article as hard_delete_article,
    )
    from bundesarchiv.app.articles import (
        save_article as save_article,
    )
    from bundesarchiv.app.collections import (
        save_collection as save_collection,
    )
    from bundesarchiv.app.result import (
        CreateResult as CreateResult,
    )
    from bundesarchiv.app.result import (
        SaveResult as SaveResult,
    )

__all__ = [
    "CreateResult",
    "SaveResult",
    "create_article",
    "hard_delete_article",
    "save_article",
    "save_collection",
]

# app-``populate()`` imports this ``__init__`` before the ORM app registry is ready, so the service
# functions (which pull in the ArticleIndex model) are resolved lazily on first access (PEP 562).
_LAZY_ARTICLES = frozenset({"save_article", "create_article", "hard_delete_article"})


def __getattr__(name: str) -> Any:
    if name in _LAZY_ARTICLES:
        from bundesarchiv.app import articles

        return getattr(articles, name)
    if name == "save_collection":
        from bundesarchiv.app.collections import save_collection

        return save_collection
    if name in ("SaveResult", "CreateResult"):
        from bundesarchiv.app import result

        return getattr(result, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
