"""Worker jobs — the Postgres-backed background queue (Procrastinate, ADR 0014, Part 4.2).

Every job is a REFERENCE, never a payload: it carries only a ulid (or nothing, for the full
rebuild), and its execution re-reads canonical truth from the configured store and recomputes
(ADR 0014 §"Queue jobs are references"). So two racing edits enqueue two pointers and whichever
runs last recomputes the same final truth — jobs are idempotent and commute. The queue exists for:
retry after a failed synchronous index update (the app services enqueue here), heavier future work
(thumbnails, OCR), mirror replay, the scheduled full rebuild, and the monthly fixity check.

The tasks are thin wrappers over ``indexer.index_article`` / ``index_subtree`` / ``rebuild``; the
security logic lives there, not here. Procrastinate auto-discovers this module (it is named
``tasks`` inside an installed app), so ``@app.task`` registration happens on Django startup.

Scheduled reconcile: ``full_rebuild`` is registered periodic on the ``BUNDESARCHIV_RECONCILE_CRON``
schedule (hourly default) — a periodic full rebuild bounds every missed incremental update (ADR
0014 §"Scheduled reconcile"). config_version drift is handled at worker startup by the
``ensure_index_current`` management command (see docs/adr/0014).
"""

import contextlib
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import httpx2
from django.conf import settings
from django.core.management import call_command
from procrastinate import RetryStrategy
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from bundesarchiv.app import mirror, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.push_record import PostgresPushRecord
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore
from bundesarchiv.persistence.objectstore import ObjectStore

#: Bounded exponential backoff for the push job. A down/slow WebDAV server is the EXPECTED failure
#: mode (ADR 0005): retry a handful of times with growing waits (~3s, 9s, 27s, 81s), then PARK the
#: job (max_attempts reached -> Procrastinate marks it failed); the daily reconcile pushes what a
#: parked job would have (ADR 0020 "Loss window").
_MIRROR_RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)

#: The fixity check's schedule (ADR 0019 "Fixity"): monthly, 04:00 on the first.
_VERIFY_CRON = "0 4 1 * *"

#: A connect to the system of record that takes longer than 5 s is a partition, not a slow server:
#: fail the attempt then, not after the 30 s a slow answer may take, so the one worker moves on.
_MIRROR_TIMEOUT = httpx2.Timeout(30, connect=5)


def canonical_store() -> ObjectStore:
    """The canonical store a job re-reads truth from (ADR 0005/0014). Resolved per job — jobs carry
    references, never a store handle. Monkeypatched in tests to point at an in-memory store."""
    return Archive.canonical().store


def _mirror_configured() -> bool:
    """Whether a system of record is configured — the settings predicate shared by
    ``mirror_store()`` and the enqueue wrappers, so the enqueue path can answer "is mirroring on"
    without building a client (and its eager SSL-context load) just to throw it away."""
    return bool(settings.BUNDESARCHIV_MIRROR_DAV_URL)


def mirror_store() -> ObjectStore | None:
    """Build the system of record's WebDAV store from settings (ADR 0020), or None when none is
    configured.

    When ``BUNDESARCHIV_MIRROR_DAV_URL`` is unset (the common dev case) this returns None and every
    mirror job / enqueue becomes a clean no-op. Constructed per job from settings (jobs carry
    references, never a store handle); monkeypatched in tests."""
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
    """Reference job: reindex ONE Article by ulid, recomputing from current canonical truth."""
    indexer.index_article(canonical_store(), ulid)


@app.task(name="reindex_subtree")
def reindex_subtree(collection_ulid: str) -> None:
    """Reference job: reindex the subtree rooted at ``collection_ulid`` from current canonical."""
    indexer.index_subtree(canonical_store(), collection_ulid)


@app.task(name="full_rebuild")
def full_rebuild() -> None:
    """Reference job: full index rebuild from canonical — the scheduled reconcile net (ADR 0014).
    Also the config_version-drift remedy invoked by ``ensure_index_current``."""
    indexer.rebuild(canonical_store())


@app.task(name="generate_thumbnail")
def generate_thumbnail(ulid: str, content_hash: str) -> None:
    """Reference job (Part 4.3): derive the WebP thumbnail for the media file with ``content_hash``
    on Article ``ulid``, re-reading it from current canonical and writing to the LOCAL derived
    thumbnail cache (``BUNDESARCHIV_THUMBNAIL_ROOT``). A no-op for a file without a renderer or one no
    longer on the Article; idempotent. The thumbnail is a prunable cache, never archive truth (README
    runbook)."""
    thumbnails.generate_thumbnail(
        canonical_store(), ulid, content_hash, Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    )


@app.periodic(cron=settings.BUNDESARCHIV_RECONCILE_CRON)
@app.task(name="reconcile")
def reconcile(timestamp: int) -> None:
    """The scheduled reconcile (ADR 0014): a periodic full rebuild that restores the index
    invariant no matter what any incremental path missed. Hourly by default
    (``BUNDESARCHIV_RECONCILE_CRON``). ``timestamp`` is the tick Procrastinate passes to a periodic
    task; it is unused here (the job is a pure reference — it recomputes from current canonical)."""
    indexer.rebuild(canonical_store())


@app.periodic(cron=_VERIFY_CRON)
@app.task(name="verify")
def verify(timestamp: int) -> None:
    """The monthly fixity check (ADR 0019): ``manage.py verify`` over the canonical archive. Its
    report goes to the worker's output; a finding raises ``CommandError`` and so fails the job.
    ``timestamp`` is the periodic tick (unused)."""
    call_command("verify")


# --- mirror replay + reconcile (Part 4.9) ----------------------------------------


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
        mirror.push(Archive.of(canonical_store()), remote, PostgresPushRecord(), ulid)
    finally:
        _close_mirror(remote)  # release the per-job httpx2.Client even when the push raises


@app.task(name="mirror_delete_article", retry=_MIRROR_RETRY)
def mirror_delete_article(ulid: str) -> None:
    """Reference job (ADR 0020 "Hard delete"): take the hard-deleted Article ``ulid`` off the
    system of record, then out of the push record. A no-op when no system of record is configured.
    Idempotent; a failed delete raises, which triggers the bounded retry (``_MIRROR_RETRY``)."""
    remote = mirror_store()
    if remote is None:
        return
    try:
        mirror.delete_article(Archive.of(canonical_store()), remote, PostgresPushRecord(), ulid)
    finally:
        _close_mirror(remote)


@app.periodic(cron=settings.BUNDESARCHIV_MIRROR_RECONCILE_CRON)
@app.task(name="mirror_reconcile")
def mirror_reconcile(timestamp: int = 0) -> dict[str, object]:
    """The scheduled reconcile (ADR 0020): pushes what any push job missed, rebuilds a lost push
    record, and reports what it leaves alone, keys changed on the system of record and keys only
    there, which it never deletes. Daily by default (``BUNDESARCHIV_MIRROR_RECONCILE_CRON``). The
    findings go to the log as warnings; the task result, which the worker logs, is how many keys
    each holds. A no-op returning ``skipped=True`` when no system of record is configured.
    ``timestamp`` is the periodic tick (unused; the sweep recomputes from canonical)."""
    remote = mirror_store()
    if remote is None:
        return {"skipped": True}
    try:
        report = mirror.reconcile(Archive.of(canonical_store()), remote, PostgresPushRecord())
    finally:
        _close_mirror(remote)  # release the per-job httpx2.Client even when the sweep raises
    return {finding: len(keys) for finding, keys in asdict(report).items()}


def _close_mirror(store: ObjectStore) -> None:
    """Close the store's owned transport if any — a no-op, so test fakes need no ``close``."""
    if isinstance(store, WebDavObjectStore):
        store.close()


# --- enqueue wrappers the app services call --------------------------------------


def enqueue_reindex_article(ulid: str) -> None:
    """Enqueue a ``reindex_article`` reference job (the app services' retry net on a failed
    synchronous index update, ADR 0014)."""
    reindex_article.defer(ulid=ulid)


def enqueue_reindex_subtree(collection_ulid: str) -> None:
    """Enqueue a ``reindex_subtree`` reference job (retry net for a failed subtree reindex)."""
    reindex_subtree.defer(collection_ulid=collection_ulid)


def enqueue_generate_thumbnail(ulid: str, content_hash: str) -> None:
    """Enqueue a ``generate_thumbnail`` reference job for one file on Article ``ulid`` (the app
    services call this for image and PDF media on save/create — Part 4.3). Re-enqueuing the same file is
    harmless (the job is idempotent and the cache key is the hash)."""
    generate_thumbnail.defer(ulid=ulid, content_hash=content_hash)


def enqueue_mirror_push(ulid: str) -> None:
    """Enqueue a ``mirror_push`` reference job for the saved Article or Collection ``ulid``. The app
    services call this AFTER a canonical write; the push is async and never blocks the request. A
    clean no-op when no system of record is configured (do not churn the queue for a feature that
    is off). A push already queued for ``ulid`` stands in for this one: it reads current truth when
    it runs.

    Checks ``_mirror_configured()`` rather than ``mirror_store()`` so this path never constructs a
    client (GH #20): building one only to discard it leaked a fresh ``httpx2.Client`` — with its
    eager SSL-context load — on every canonical write when mirroring is configured."""
    if not _mirror_configured():
        return  # mirror unset -> nothing to enqueue
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
    from procrastinate.testing import InMemoryConnector

    connector = InMemoryConnector()
    with app.replace_connector(connector):
        defer()  # the test hands a zero-arg callable that defers jobs onto the connector
        app.run_worker(
            wait=False, install_signal_handlers=False, listen_notify=False, delete_jobs="never"
        )
    return len(connector.finished_jobs)
