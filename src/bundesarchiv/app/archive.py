"""The ``Archive`` handle — the canonical store and the repositories over it, as one value.

Lives in the app shell rather than ``persistence/`` because ``canonical()`` reads Django settings,
and the core never imports Django (ADR 0005).
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository


@dataclass(frozen=True, slots=True)
class Archive:
    """One archive: the ``ObjectStore`` port (ADR 0005) plus the two repositories built over it.

    ``store`` is for callers that need the stored objects themselves rather than the Articles and
    Collections in them. Everything else goes through ``articles`` / ``collections``.
    """

    store: ObjectStore
    articles: ArticleRepository
    collections: CollectionRepository

    @classmethod
    def of(cls, store: ObjectStore) -> Archive:
        """The archive held by ``store`` — the seam a test builds over an in-memory adapter."""
        return cls(
            store=store,
            articles=ArticleRepository(store),
            collections=CollectionRepository(store),
        )

    @classmethod
    def canonical(cls) -> Archive:
        """The canonical archive from ``BUNDESARCHIV_CANONICAL_ROOT``, the one place that builds the
        CANONICAL store. Built per call, so a settings override takes effect."""
        return cls.of(LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT)))
