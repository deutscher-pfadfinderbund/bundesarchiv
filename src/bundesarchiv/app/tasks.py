"""Worker jobs — the Postgres-backed background queue (Procrastinate, ADR 0014, Part 4.2).

Every job is a REFERENCE, never a payload: it carries only a ulid (or nothing, for the full
rebuild), and its execution re-reads canonical truth from the configured store and recomputes
(ADR 0014 §"Queue jobs are references"). So two racing edits enqueue two pointers and whichever
runs last recomputes the same final truth — jobs are idempotent and commute. The queue exists for:
retry after a failed synchronous index update (the app services enqueue here), heavier future work
(thumbnails, OCR), mirror replay, and the scheduled full rebuild.

The tasks are thin wrappers over ``indexer.index_article`` / ``index_subtree`` / ``rebuild``; the
security logic lives there, not here. Procrastinate auto-discovers this module (it is named
``tasks`` inside an installed app), so ``@app.task`` registration happens on Django startup.

Scheduled reconcile: ``full_rebuild`` is registered periodic on the ``BUNDESARCHIV_RECONCILE_CRON``
schedule (hourly default) — a periodic full rebuild bounds every missed incremental update (ADR
0014 §"Scheduled reconcile"). config_version drift is handled at worker startup by the
``ensure_index_current`` management command (see docs/adr/0014).
"""

from collections.abc import Callable
from pathlib import Path

from django.conf import settings
from procrastinate.contrib.django import app

from bundesarchiv.app import thumbnails
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.objectstore import ObjectStore


def canonical_store() -> ObjectStore:
    """Build the canonical files-store a job re-reads truth from (ADR 0005/0014). Constructed here,
    per job, from settings — jobs carry references, never a store handle. Monkeypatched in tests to
    point at an in-memory store."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


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
def generate_thumbnail(content_hash: str) -> None:
    """Reference job (Part 4.3): derive the WebP thumbnail for the media blob with ``content_hash``,
    re-reading the blob from current canonical and writing to the LOCAL derived thumbnail cache
    (``BUNDESARCHIV_THUMBNAIL_ROOT``). A no-op for a non-image blob or a hash no longer in canonical;
    idempotent. The thumbnail is a prunable cache, never archive truth (README runbook)."""
    thumbnails.generate_thumbnail(
        canonical_store(), content_hash, Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
    )


@app.periodic(cron=settings.BUNDESARCHIV_RECONCILE_CRON)
@app.task(name="reconcile")
def reconcile(timestamp: int) -> None:
    """The scheduled reconcile (ADR 0014): a periodic full rebuild that restores the index
    invariant no matter what any incremental path missed. Hourly by default
    (``BUNDESARCHIV_RECONCILE_CRON``). ``timestamp`` is the tick Procrastinate passes to a periodic
    task; it is unused here (the job is a pure reference — it recomputes from current canonical)."""
    indexer.rebuild(canonical_store())


# --- enqueue wrappers the app services call --------------------------------------


def enqueue_reindex_article(ulid: str) -> None:
    """Enqueue a ``reindex_article`` reference job (the app services' retry net on a failed
    synchronous index update, ADR 0014)."""
    reindex_article.defer(ulid=ulid)


def enqueue_reindex_subtree(collection_ulid: str) -> None:
    """Enqueue a ``reindex_subtree`` reference job (retry net for a failed subtree reindex)."""
    reindex_subtree.defer(collection_ulid=collection_ulid)


def enqueue_generate_thumbnail(content_hash: str) -> None:
    """Enqueue a ``generate_thumbnail`` reference job for one image blob (the app services call this
    for image media on save/create — Part 4.3). Content-hash-keyed, so re-enqueuing the same blob is
    harmless (the job is idempotent and the cache key is the hash)."""
    generate_thumbnail.defer(content_hash=content_hash)


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
