"""What the worker jobs do, given what they work on: the archive, the system of record, the push
record. ``tasks`` resolves those from settings and calls in (ADR 0014)."""

import contextlib
import logging
import time
from collections.abc import Callable, Generator
from dataclasses import asdict

from bundesarchiv.app import mirror, stats
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.mirror import PushRecord
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.objectstore import ObjectStore

logger = logging.getLogger(__name__)


def reconcile(archive: Archive, enqueue_missing_text: Callable[[Archive], None]) -> None:
    """The full rebuild that bounds whatever an incremental path missed (ADR 0014). The archive
    stats and the page-text net after it never fail the rebuild that already committed."""
    rows_before = ArticleIndex.objects.count()  # the drift the rebuild is about to repair
    indexer.rebuild(archive.store)
    try:
        stats.log_archive_stats(archive.store, index_rows_before=rows_before)
    except Exception:
        logger.exception("archive stats failed")
    try:
        enqueue_missing_text(archive)
    except Exception:
        logger.exception("page text enqueue failed")


def mirror_push(archive: Archive, remote: ObjectStore, record: PushRecord, ulid: str) -> None:
    """Push the saved Article or Collection ``ulid`` to ``remote`` as current canonical truth has
    it, only what ``record`` does not hold already. A no-op for a ulid no longer saved. A failed
    write raises."""
    with _summary("mirror_push", ulid=ulid) as fields:
        sent = mirror.push(archive, remote, record, ulid)
        fields |= {"sent": sent.keys, "sent_bytes": sent.bytes}


def mirror_delete_article(
    archive: Archive, remote: ObjectStore, record: PushRecord, ulid: str
) -> None:
    """Take the hard-deleted Article ``ulid`` off ``remote``, then out of ``record`` (ADR 0020
    "Hard delete"). Idempotent; a failed delete raises."""
    with _summary("mirror_delete_article", ulid=ulid):
        mirror.delete_article(archive, remote, record, ulid)


def mirror_reconcile(
    archive: Archive, remote: ObjectStore, record: PushRecord
) -> dict[str, object]:
    """How many keys each finding of ``mirror.reconcile`` holds."""
    with _summary("mirror_reconcile") as fields:
        report = mirror.reconcile(archive, remote, record)
        counts: dict[str, object] = {
            finding: len(keys)
            for finding, keys in asdict(report).items()
            if isinstance(keys, tuple)
        }
        fields |= counts | {"sent_bytes": report.sent_bytes, "remote_keys": report.remote_keys}
        if isinstance(remote, WebDavObjectStore):
            # the size is for the dashboard only: a failed query never fails the sweep
            with contextlib.suppress(Exception):
                if (size := remote.root_size()) is not None:
                    fields["remote_bytes"] = size
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
