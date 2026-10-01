"""What runs after every canonical write: the synchronous index update with its retry fallback
(ADR 0014), then the enqueue of the push or delete on the system of record (ADR 0020).

The write services name what they wrote; this module decides what that means for the index and
the mirror. Nothing here raises: the canonical write already stood. ``run`` answers whether the
index caught up in-request — the bit every write route must show when it is False.

``index_article``, ``index_subtree`` and the ``enqueue_*`` jobs are module-level names so tests can
monkeypatch these genuine boundaries (the index adapter, the worker queue).
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.tasks import (
    enqueue_mirror_delete_article,
    enqueue_mirror_push,
    enqueue_reindex_article,
    enqueue_reindex_subtree,
)
from bundesarchiv.domain.models import Ulid
from bundesarchiv.index.indexer import SYNC_LOCK_TIMEOUT_MS, index_article, index_subtree


@dataclass(frozen=True, slots=True)
class SavedArticle:
    """An Article was saved (a Papierkorb mark included): reindex its row, push it."""

    ulid: Ulid


@dataclass(frozen=True, slots=True)
class RemovedArticle:
    """An Article left canonical for good: its row drops on reindex, its delete is enqueued."""

    ulid: Ulid


@dataclass(frozen=True, slots=True)
class SavedCollection:
    """A Collection was saved without moving the visibility of any Article: push it."""

    ulid: Ulid


@dataclass(frozen=True, slots=True)
class MovedCollection:
    """A Collection was saved and the visibility of the Articles under it moved: reindex its whole
    subtree, push it."""

    ulid: Ulid


type Written = SavedArticle | RemovedArticle | SavedCollection | MovedCollection


def run(archive: Archive, written: Written) -> bool:
    """Sync the index for ``written``, enqueueing a retry if that fails, then enqueue the mirror
    job. True iff the index is current."""
    match written:
        case SavedArticle(ulid):
            index_updated, mirror = _article_synced(archive, ulid), enqueue_mirror_push
        case RemovedArticle(ulid):
            index_updated, mirror = _article_synced(archive, ulid), enqueue_mirror_delete_article
        case MovedCollection(ulid):
            index_updated = _synced(
                lambda: index_subtree(archive.store, ulid, lock_timeout_ms=SYNC_LOCK_TIMEOUT_MS),
                lambda: enqueue_reindex_subtree(ulid),
            )
            mirror = enqueue_mirror_push
        case SavedCollection():
            index_updated, mirror = True, enqueue_mirror_push
    # the write stood; the daily reconcile does what a lost job would have
    with contextlib.suppress(Exception):
        mirror(written.ulid)
    return index_updated


def _article_synced(archive: Archive, ulid: Ulid) -> bool:
    return _synced(
        lambda: index_article(archive.store, ulid, lock_timeout_ms=SYNC_LOCK_TIMEOUT_MS),
        lambda: enqueue_reindex_article(ulid),
    )


def _synced(index: Callable[[], None], retry: Callable[[], None]) -> bool:
    try:
        index()
    except Exception:  # noqa: BLE001 — the canonical write stood; the sync index is best-effort, retry via queue
        with contextlib.suppress(Exception):  # the periodic full rebuild heals a lost retry
            retry()
        return False
    return True
