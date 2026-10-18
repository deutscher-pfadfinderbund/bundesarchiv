"""The ``Archive`` handle — the canonical store, the repositories over it and its index, as one
value (ADR 0024).

Lives in the app shell rather than ``persistence/`` because ``canonical()`` reads Django settings,
and the core never imports Django (ADR 0005).
"""

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

if TYPE_CHECKING:
    from bundesarchiv.index.refresh import Index

#: Builds an index over the store it is given — the only way an ``Archive`` gets one.
type IndexOver = Callable[[ObjectStore], Index]


def _postgres_index(store: ObjectStore) -> Index:
    # imported here, so this module's many importers do not load the ORM models
    from bundesarchiv.index.refresh import PostgresIndex

    return PostgresIndex(store)


@dataclass(frozen=True, slots=True)
class Archive:
    """One archive: the ``ObjectStore`` port (ADR 0005) plus the two repositories and the index,
    all built over it.

    ``store`` is for callers that need the stored objects themselves rather than the Articles and
    Collections in them. Everything else goes through ``articles`` / ``collections``.
    """

    store: ObjectStore
    index_over: InitVar[IndexOver]
    articles: ArticleRepository = field(init=False)
    collections: CollectionRepository = field(init=False)
    index: Index = field(init=False)

    def __post_init__(self, index_over: IndexOver) -> None:
        object.__setattr__(self, "articles", ArticleRepository(self.store))
        object.__setattr__(self, "collections", CollectionRepository(self.store))
        object.__setattr__(self, "index", index_over(self.store))

    @classmethod
    def of(cls, store: ObjectStore, index: IndexOver = _postgres_index) -> Archive:
        """The archive held by ``store`` — the seam a test builds over in-memory adapters."""
        return cls(store, index)

    @classmethod
    def canonical(cls) -> Archive:
        """Built per call, so a settings override takes effect. Only a test sets
        ``BUNDESARCHIV_INDEX``, an ``IndexOver``; the WSGI entry refuses to serve with it."""
        return cls.of(
            LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT)),
            getattr(settings, "BUNDESARCHIV_INDEX", _postgres_index),
        )
