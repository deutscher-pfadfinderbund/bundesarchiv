"""The worker's jobs as values, and what each does (``run``). A job carries references, never
payloads, and recomputes from current canonical when it runs, so jobs are idempotent and commute
(ADR 0014). ``tasks`` puts them on the queue and resolves what they work on from settings.
"""

import contextlib
import logging
import time
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import assert_never

from bundesarchiv.app import media_text, mirror, stats, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.mirror import PushRecord, RecordKind
from bundesarchiv.domain.models import ULID
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.persistence.objectstore import ObjectStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReindexArticle:
    ulid: ULID


@dataclass(frozen=True, slots=True)
class ReindexSubtree:
    collection_ulid: ULID


@dataclass(frozen=True, slots=True)
class Thumbnail:
    """Render the file ``content_hash`` of Article ``ulid``."""

    ulid: ULID
    content_hash: str


@dataclass(frozen=True, slots=True)
class PageText:
    """Read the page text of Article ``ulid``'s files (ADR 0023)."""

    ulid: ULID


@dataclass(frozen=True, slots=True)
class MirrorPush:
    """Push the saved record ``ulid`` to the system of record (ADR 0020)."""

    ulid: ULID
    kind: RecordKind


@dataclass(frozen=True, slots=True)
class MirrorDelete:
    """Take the hard-deleted Article ``ulid`` off the system of record (ADR 0020 "Hard delete")."""

    ulid: ULID


type Job = ReindexArticle | ReindexSubtree | Thumbnail | PageText | MirrorPush | MirrorDelete

# a plain alias, not `type`: `isinstance` takes it
MirrorJob = MirrorPush | MirrorDelete


@dataclass(frozen=True, slots=True)
class Deps:
    """What the jobs work on. ``mirror`` opens the system of record for one job and closes it
    after; it holds None when none is configured, and a mirror job is a no-op then."""

    archive: Archive
    thumbnail_root: Path
    mirror: Callable[[], AbstractContextManager[ObjectStore | None]]
    record: PushRecord


def run(job: Job, deps: Deps) -> None:
    """Do ``job`` against current canonical. A failed mirror job raises, so the queue retries it."""
    if isinstance(job, MirrorJob):
        with deps.mirror() as remote:
            if remote is not None:
                _mirror(job, deps.archive, remote, deps.record)
        return
    match job:
        case ReindexArticle(ulid):
            indexer.index_article(deps.archive.store, ulid)
        case ReindexSubtree(collection_ulid):
            indexer.index_subtree(deps.archive.store, collection_ulid)
        case Thumbnail(ulid, content_hash):
            thumbnails.generate_thumbnail(
                deps.archive.store, ulid, content_hash, deps.thumbnail_root
            )
        case PageText(ulid):
            media_text.fill(deps.archive, ulid)
        case _:
            assert_never(job)


def _mirror(job: MirrorJob, archive: Archive, remote: ObjectStore, record: PushRecord) -> None:
    match job:
        case MirrorPush(ulid, kind):
            with _summary("mirror_push", ulid=ulid) as fields:
                sent = mirror.push(archive, remote, record, ulid, kind)
                fields |= {"sent": sent.keys, "sent_bytes": sent.bytes}
        case MirrorDelete(ulid):
            with _summary("mirror_delete_article", ulid=ulid):
                mirror.delete_article(archive, remote, record, ulid)
        case _:
            assert_never(job)


def reconcile(archive: Archive, enqueue: Callable[[Job], None]) -> None:
    """The full rebuild that bounds whatever an incremental path missed (ADR 0014), then a
    ``PageText`` job per Article ``media_text.missing`` names: one job per Article, so a file that
    hangs or crashes the reader costs only its own job. The archive stats and the page-text net
    never fail the rebuild that already committed."""
    rows_before = ArticleIndex.objects.count()  # the drift the rebuild is about to repair
    indexer.rebuild(archive.store)
    try:
        stats.log_archive_stats(archive.store, index_rows_before=rows_before)
    except Exception:
        logger.exception("archive stats failed")
    try:
        for ulid in media_text.missing(archive):
            enqueue(PageText(ulid))
    except Exception:
        logger.exception("page text enqueue failed")


def mirror_reconcile(
    archive: Archive,
    remote: ObjectStore,
    record: PushRecord,
    *,
    size: Callable[[], int | None],
) -> dict[str, object]:
    """How many keys each finding of ``mirror.reconcile`` holds. ``size`` asks ``remote`` how many
    bytes it holds, None when it does not say."""
    with _summary("mirror_reconcile") as fields:
        report = mirror.reconcile(archive, remote, record)
        counts: dict[str, object] = {
            finding: len(keys)
            for finding, keys in asdict(report).items()
            if isinstance(keys, tuple)
        }
        fields |= counts | {"sent_bytes": report.sent_bytes, "remote_keys": report.remote_keys}
        # the size is for the dashboard only: a failed query never fails the sweep
        with contextlib.suppress(Exception):
            if (remote_bytes := size()) is not None:
                fields["remote_bytes"] = remote_bytes
    return counts


@contextlib.contextmanager
def _summary(job: str, **fixed: object) -> Generator[dict[str, object]]:
    """Log the mirror job's one summary record: INFO `outcome=ok` when the body returns, ERROR
    `outcome=failed` with `exception_class` and the traceback when it raises (then re-raised, so
    Procrastinate's retry still runs). `task` is not `job`: Procrastinate's own records use `job` for
    an object. The body adds its counts to the yielded dict."""
    fields: dict[str, object] = {"task": job, **fixed}
    started = time.monotonic()
    try:
        yield fields
    except Exception as exc:
        fields |= {"outcome": "failed", "exception_class": type(exc).__name__}
        fields["seconds"] = round(time.monotonic() - started, 3)
        logger.exception("%s failed", job, extra=fields)
        raise
    fields |= {"outcome": "ok", "seconds": round(time.monotonic() - started, 3)}
    logger.info("%s done", job, extra=fields)
