"""The index as the write path sees it (ADR 0024): refresh one Article's row, refresh a
Collection's subtree. Each adapter is built over the archive's store. ``PostgresIndex`` is the
index; ``InMemoryIndex`` is the test fake."""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from bundesarchiv.domain.models import Ulid, Version
from bundesarchiv.index.indexer import index_article, index_subtree
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: Long enough to outwait a typical full rebuild; on timeout the retry job reindexes.
SYNC_LOCK_TIMEOUT_MS = 5000


class Index(Protocol):
    """Best effort: the write already stood, so a caller survives a raise (ADR 0014)."""

    def refresh_article(self, ulid: Ulid) -> None:
        """Recompute ``ulid``'s row from the store, or drop it when the Article is gone."""

    def refresh_subtree(self, collection_ulid: Ulid) -> None:
        """Recompute the row of every Article under ``collection_ulid``."""


@dataclass(frozen=True, slots=True)
class PostgresIndex:
    """``ArticleIndex`` rows computed from ``store``; a lock wait past ``lock_timeout_ms`` raises
    with nothing written (ADR 0014)."""

    store: ObjectStore
    lock_timeout_ms: int = SYNC_LOCK_TIMEOUT_MS

    def refresh_article(self, ulid: Ulid) -> None:
        index_article(self.store, ulid, lock_timeout_ms=self.lock_timeout_ms)

    def refresh_subtree(self, collection_ulid: Ulid) -> None:
        index_subtree(self.store, collection_ulid, lock_timeout_ms=self.lock_timeout_ms)


#: A refresh the fake was asked for, and the version ``store`` held at that moment (None: absent).
type Refresh = tuple[Literal["article", "subtree"], Ulid, Version | None]


@dataclass
class InMemoryIndex:
    """Records each refresh with what ``store`` held then, and computes no rows; with ``failing``
    every refresh raises after it is recorded."""

    store: ObjectStore
    failing: bool = False
    refreshed: list[Refresh] = field(default_factory=list)

    def refresh_article(self, ulid: Ulid) -> None:
        try:
            version: Version | None = ArticleRepository(self.store).load(ulid).version
        except NotFound:
            version = None
        self._record(("article", ulid, version))

    def refresh_subtree(self, collection_ulid: Ulid) -> None:
        try:
            version: Version | None = CollectionRepository(self.store).load(collection_ulid).version
        except NotFound:
            version = None
        self._record(("subtree", collection_ulid, version))

    def _record(self, refresh: Refresh) -> None:
        self.refreshed.append(refresh)
        if self.failing:
            raise RuntimeError("index down")
