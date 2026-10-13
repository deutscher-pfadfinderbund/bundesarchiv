"""A job carries references (a ulid, a content hash) and recomputes from current canonical when
it runs, so jobs are idempotent and commute (ADR 0014).
"""

import contextlib
import logging
import time
from collections.abc import Callable, Generator
from dataclasses import asdict
from pathlib import Path

import httpx2  # noqa: TID251
from django.conf import settings
from django.core.management import call_command
from procrastinate import RetryStrategy  # noqa: TID251
from procrastinate.contrib.django import app  # noqa: TID251
from procrastinate.exceptions import AlreadyEnqueued  # noqa: TID251

from bundesarchiv.app import media_text, mirror, stats, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.push_record import PostgresPushRecord
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.objectstore import ObjectStore

logger = logging.getLogger(__name__)

#: Bounded exponential backoff for the push job. A down/slow WebDAV server is the EXPECTED failure
#: mode (ADR 0005): retry a handful of times with growing waits (~3s, 9s, 27s, 81s), then PARK the
#: job (max_attempts reached -> Procrastinate marks it failed); the daily reconcile pushes what a
#: parked job would have (ADR 0020 "Loss window").
_MIRROR_RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)

#: ADR 0019 "Fixity".
_VERIFY_CRON = "0 4 1 * *"

#: A connect to the system of record that takes longer than 5 s is a partition, not a slow server:
#: fail the attempt then, not after the 30 s a slow answer may take, so the one worker moves on.
_MIRROR_TIMEOUT = httpx2.Timeout(30, connect=5)


def canonical_store() -> ObjectStore:
    """The canonical store a job re-reads truth from (ADR 0005/0014). Resolved per job — jobs carry
    references, never a store handle. Monkeypatched in tests to point at an in-memory store."""
    return Archive.canonical().store


def _mirror_configured() -> bool:
    return bool(settings.BUNDESARCHIV_MIRROR_DAV_URL)


def mirror_store() -> ObjectStore | None:
    """Built per job, since every job closes it (``_close_mirror``)."""
    url: str | None = settings.BUNDESARCHIV_MIRROR_DAV_URL
    if not url:
        return None
    user: str | None = settings.BUNDESARCHIV_MIRROR_DAV_USER
    password: str | None = settings.BUNDESARCHIV_MIRROR_DAV_PASSWORD
    auth: tuple[str, str] | None = (user, password or "") if user is not None else None
    return WebDavObjectStore(httpx2.Client(base_url=url, auth=auth, timeout=_MIRROR_TIMEOUT))


# --- reference tasks -------------------------------------------------------------


@app.task(name="reindex_article")
def reindex_article(ulid: str) -> None:
    indexer.index_article(canonical_store(), ulid)


@app.task(name="reindex_subtree")
def reindex_subtree(collection_ulid: str) -> None:
    indexer.index_subtree(canonical_store(), collection_ulid)


@app.task(name="generate_thumbnail")
def generate_thumbnail(ulid: str, content_hash: str) -> None:
    thumbnails.generate_thumbnail(
        canonical_store(), ulid, content_hash, Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    )


@app.task(name="extract_media_text")
def extract_media_text(ulid: str) -> None:
    """Reference job (ADR 0023): read the page text of Article ``ulid``'s files that have none yet,
    from current canonical, into ``MediaText``. A no-op for an Article gone or fully read."""
    media_text.fill(Archive.canonical(), ulid)


@app.periodic(cron=settings.BUNDESARCHIV_RECONCILE_CRON)
@app.task(name="reconcile")
def reconcile(timestamp: int) -> None:
    """The scheduled full rebuild that bounds whatever an incremental path missed (ADR 0014)."""
    store = canonical_store()
    rows_before = ArticleIndex.objects.count()  # the drift the rebuild is about to repair
    indexer.rebuild(store)
    try:
        stats.log_archive_stats(store, index_rows_before=rows_before)
    except Exception:  # the dashboard numbers never fail the rebuild that already committed
        logger.exception("archive stats failed")
    try:
        enqueue_missing_text(Archive.of(store))
    except Exception:  # nor does the page-text net
        logger.exception("page text enqueue failed")


@app.periodic(cron=_VERIFY_CRON)
@app.task(name="verify")
def verify(timestamp: int) -> None:
    """A finding raises ``CommandError`` and so fails the job."""
    call_command("verify")


# --- mirror jobs (ADR 0020) ------------------------------------------------------


@app.task(name="mirror_push", retry=_MIRROR_RETRY)
def mirror_push(ulid: str) -> None:
    """Reference job (ADR 0014, 0020): push the saved Article or Collection ``ulid`` to the system
    of record as current canonical truth has it, only what the push record does not hold already.
    A no-op when no system of record is configured, and for a ulid no longer saved. A failed write
    raises, which triggers the bounded retry (``_MIRROR_RETRY``)."""
    remote = mirror_store()
    if remote is None:
        return
    try:
        with _summary("mirror_push", ulid=ulid) as fields:
            sent = mirror.push(Archive.of(canonical_store()), remote, PostgresPushRecord(), ulid)
            fields |= {"sent": sent.keys, "sent_bytes": sent.bytes}
    finally:
        _close_mirror(remote)


@app.task(name="mirror_delete_article", retry=_MIRROR_RETRY)
def mirror_delete_article(ulid: str) -> None:
    """Reference job (ADR 0020 "Hard delete"): take the hard-deleted Article ``ulid`` off the
    system of record, then out of the push record. A no-op when no system of record is configured.
    Idempotent; a failed delete raises, which triggers the bounded retry (``_MIRROR_RETRY``)."""
    remote = mirror_store()
    if remote is None:
        return
    try:
        with _summary("mirror_delete_article", ulid=ulid):
            mirror.delete_article(Archive.of(canonical_store()), remote, PostgresPushRecord(), ulid)
    finally:
        _close_mirror(remote)


@app.periodic(cron=settings.BUNDESARCHIV_MIRROR_RECONCILE_CRON)
@app.task(name="mirror_reconcile")
def mirror_reconcile(timestamp: int = 0) -> dict[str, object]:
    remote = mirror_store()
    if remote is None:
        return {"skipped": True}
    try:
        with _summary("mirror_reconcile") as fields:
            report = mirror.reconcile(Archive.of(canonical_store()), remote, PostgresPushRecord())
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
    finally:
        _close_mirror(remote)
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


def _close_mirror(store: ObjectStore) -> None:
    """Close the store's owned transport if any — a no-op, so test fakes need no ``close``."""
    if isinstance(store, WebDavObjectStore):
        store.close()


# --- enqueue wrappers the app services call --------------------------------------


def enqueue_reindex_article(ulid: str) -> None:
    reindex_article.defer(ulid=ulid)


def enqueue_reindex_subtree(collection_ulid: str) -> None:
    reindex_subtree.defer(collection_ulid=collection_ulid)


def enqueue_generate_thumbnail(ulid: str, content_hash: str) -> None:
    """Re-enqueuing the same file is harmless: the job is idempotent and the cache key is the hash."""
    generate_thumbnail.defer(ulid=ulid, content_hash=content_hash)


def enqueue_extract_media_text(ulid: str) -> None:
    """Enqueue an ``extract_media_text`` reference job for Article ``ulid``. A job already queued
    for ``ulid`` stands in for this one: it reads current truth when it runs."""
    with contextlib.suppress(AlreadyEnqueued):
        extract_media_text.configure(queueing_lock=f"extract_media_text:{ulid}").defer(ulid=ulid)


def enqueue_missing_text(archive: Archive) -> None:
    """Enqueue an ``extract_media_text`` job for each Article ``media_text.missing`` names: one job
    per Article, so a file that hangs or crashes the reader costs only its own job."""
    for ulid in media_text.missing(archive):
        enqueue_extract_media_text(ulid)


def enqueue_mirror_push(ulid: str) -> None:
    """A push already queued for ``ulid`` stands in for this one: it reads current truth when it
    runs. ``_mirror_configured()``, not ``mirror_store()``: building a client to drop it costs an
    eager SSL-context load."""
    if not _mirror_configured():
        return
    with contextlib.suppress(AlreadyEnqueued):
        mirror_push.configure(queueing_lock=f"mirror_push:{ulid}").defer(ulid=ulid)


def enqueue_mirror_delete_article(ulid: str) -> None:
    """Enqueue a ``mirror_delete_article`` reference job for the hard-deleted Article ``ulid``,
    AFTER the local delete. A no-op when no system of record is configured, as
    ``enqueue_mirror_push``."""
    if not _mirror_configured():
        return
    mirror_delete_article.defer(ulid=ulid)


# --- in-test worker harness ------------------------------------------------------


def run_worker_once_in_test(defer: Callable[[], None]) -> int:
    """Deterministic worker-loop smoke for tests: swap in Procrastinate's InMemoryConnector, run
    the ``defer`` callback to enqueue job(s) onto it, then drain the worker ONCE (one-shot, no
    wait, no signal handlers, no LISTEN/NOTIFY). Returns the number of jobs processed.

    The InMemoryConnector holds only the queue; the tasks still write the real index DB, so this
    exercises the true task functions end-to-end without a live worker process or broker."""
    from procrastinate.testing import InMemoryConnector  # noqa: TID251

    connector = InMemoryConnector()
    with app.replace_connector(connector):
        defer()
        app.run_worker(
            wait=False, install_signal_handlers=False, listen_notify=False, delete_jobs="never"
        )
    return len(connector.finished_jobs)
