"""What runs after every canonical write (ADR 0013/0014): the reindex, in the request and queued
only when that fails; then the push or delete on the system of record (ADR 0020); then the jobs
that derive files from an Article's media. ``jobs`` lists them, ``run`` runs them, ``queue``
queues them for a batch.

The write services name what they wrote; this module decides what that entails. Nothing here
raises: the canonical write already stood. ``run`` answers whether the index caught up in-request —
the bit every write route must show when it is False.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import assert_never

from bundesarchiv.app import media_text, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.jobs import (
    Job,
    MirrorDelete,
    MirrorPush,
    PageText,
    ReindexArticle,
    ReindexSubtree,
    Thumbnail,
)
from bundesarchiv.app.tasks import (
    enqueue_extract_media_text,
    enqueue_generate_thumbnail,
    enqueue_mirror_delete_article,
    enqueue_mirror_push,
    enqueue_reindex_article,
    enqueue_reindex_subtree,
)
from bundesarchiv.domain.collections import moves_visibility
from bundesarchiv.domain.models import ULID, Article, Collection


@dataclass(frozen=True, slots=True)
class SavedArticle:
    """An Article was saved or created."""

    article: Article


@dataclass(frozen=True, slots=True)
class TrashedArticle:
    """An Article went into the Trash (ADR 0022); its files stayed as they were."""

    ulid: ULID


@dataclass(frozen=True, slots=True)
class RemovedArticle:
    """An Article left canonical for good."""

    ulid: ULID


@dataclass(frozen=True, slots=True)
class CreatedCollection:
    """A new Collection, which holds no Articles yet."""

    collection: Collection


@dataclass(frozen=True, slots=True)
class SavedCollection:
    """``after`` was saved over ``before``, the Collection as canonical held it."""

    before: Collection
    after: Collection


type Written = SavedArticle | TrashedArticle | RemovedArticle | CreatedCollection | SavedCollection


def jobs(written: Written) -> tuple[Job, ...]:
    """What ``written`` entails, in the order ``run`` runs it."""
    match written:
        case SavedArticle(article):
            return (ReindexArticle(article.ulid), MirrorPush(article.ulid), *derived_jobs(article))
        case TrashedArticle(ulid):
            return (ReindexArticle(ulid), MirrorPush(ulid))
        case RemovedArticle(ulid):
            return (ReindexArticle(ulid), MirrorDelete(ulid))
        case CreatedCollection(collection):
            return (MirrorPush(collection.ulid),)
        case SavedCollection(before, after):
            reindex = (ReindexSubtree(after.ulid),) if moves_visibility(before, after) else ()
            return (*reindex, MirrorPush(after.ulid))
        case _:
            assert_never(written)


def derived_jobs(article: Article) -> tuple[Thumbnail | PageText, ...]:
    """The jobs that derive files from ``article``'s media: a ``Thumbnail`` per file whose kind has
    a renderer, and one ``PageText`` when any file ``media_text.reads``."""
    tiles = tuple(
        Thumbnail(article.ulid, ref.content_hash)
        for ref in article.media
        if thumbnails.renders(ref)
    )
    text = (PageText(article.ulid),) if any(map(media_text.reads, article.media)) else ()
    return tiles + text


def run(archive: Archive, written: Written) -> bool:
    """Run ``jobs(written)``, each on its own: a reindex in the request, every other job queued.
    True iff the index is current."""
    outcomes = [_ran(archive, job) for job in jobs(written)]
    return all(outcomes)


def queue(written: Written, *, skip: tuple[type[Job], ...]) -> None:
    """Queue every job of ``written`` but those of a kind in ``skip``, each on its own: for a batch
    that does those itself."""
    for job in jobs(written):
        if not isinstance(job, skip):
            _enqueue(job)


def _ran(archive: Archive, job: Job) -> bool:
    """False iff ``job`` is a reindex the index failed in the request; it is queued then."""
    refresh: Callable[[], None]
    match job:
        case ReindexArticle(ulid):
            refresh = partial(archive.index.refresh_article, ulid)
        case ReindexSubtree(collection_ulid):
            refresh = partial(archive.index.refresh_subtree, collection_ulid)
        case _:
            _enqueue(job)
            return True
    try:
        refresh()
    except Exception:  # noqa: BLE001 — the canonical write stood; the queued reindex catches up
        _enqueue(job)
        return False
    return True


def _enqueue(job: Job) -> None:
    # the write stood; a lost reindex or page text waits for the periodic rebuild, a lost push
    # for the mirror reconcile, a lost thumbnail for rebuild_thumbnails; a lost delete shows as
    # remote_only
    with contextlib.suppress(Exception):
        match job:
            case ReindexArticle(ulid):
                enqueue_reindex_article(ulid)
            case ReindexSubtree(collection_ulid):
                enqueue_reindex_subtree(collection_ulid)
            case Thumbnail(ulid, content_hash):
                enqueue_generate_thumbnail(ulid, content_hash)
            case PageText(ulid):
                enqueue_extract_media_text(ulid)
            case MirrorPush(ulid):
                enqueue_mirror_push(ulid)
            case MirrorDelete(ulid):
                enqueue_mirror_delete_article(ulid)
            case _:
                assert_never(job)
