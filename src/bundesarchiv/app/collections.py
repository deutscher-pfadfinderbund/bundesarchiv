"""Collection write service — the canonical-then-subtree-index shell (ADR 0013 + 0014).

A Collection audience or parent edit changes the effective audience of every descendant Article,
so after the canonical save we synchronously reindex the WHOLE subtree (``index_subtree``), not a
single row. Same failure contract as the Article services: a stale ``expected_version`` raises
``Conflict`` before any index work; an index failure leaves the canonical write standing, enqueues
a reference subtree-reindex job, and returns ``index_updated=False``.

``index_subtree`` and ``enqueue_reindex_subtree`` are module-level names so the service seam is
monkeypatchable in tests.
"""

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import CreateResult, SaveResult
from bundesarchiv.app.tasks import enqueue_mirror_push, enqueue_reindex_subtree
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import Audience, Collection, Ulid, Version
from bundesarchiv.index.indexer import index_subtree
from bundesarchiv.persistence.errors import NotFound


def create_collection(
    archive: Archive,
    *,
    changed_by: str,
    name: str,
    parent_id: Ulid | None = None,
    audience: Audience | None = None,
) -> CreateResult:
    """Mint a NEW Collection (fresh ULID), save it at version 0 → v1, then reindex its subtree. A
    fresh collection is empty (a leaf, no descendants), so setting its audience at creation is safe —
    no over-exposure is possible (4.8). When ``parent_id`` is given it MUST exist (else ``NotFound``,
    fail-closed — a new node cannot dangle); a top-level collection passes ``parent_id=None``. A new
    leaf can never create a cycle, so no cycle guard is needed here (unlike a move, which is deferred).
    """
    if parent_id is not None and not _collection_exists(archive, parent_id):
        raise NotFound(f"parent collection {parent_id!r} does not exist")
    collection = Collection(
        ulid=identity.new_ulid(), name=name, parent_id=parent_id, audience=audience
    )
    new_version = archive.collections.save(collection, 0, changed_by=changed_by)  # first: v1
    index_updated = _sync_index_subtree(archive, collection.ulid)
    _enqueue_mirror(collection.ulid)
    return CreateResult(ulid=collection.ulid, version=new_version, index_updated=index_updated)


def _collection_exists(archive: Archive, ulid: Ulid) -> bool:
    """Is ``ulid`` a real saved Collection? A targeted load (1 read) rather than a full ``load_all``
    sweep — the caller maps a miss to the same refusal any invalid parent gets (no existence oracle)."""
    try:
        archive.collections.load(ulid)
    except NotFound:
        return False
    return True


def save_collection(
    archive: Archive, collection: Collection, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Save ``collection`` (CAS at ``expected_version``) then synchronously reindex its whole
    subtree — an audience/parent edit moves every descendant Article's visibility. A stale version
    raises ``Conflict`` before any index work. On index failure the canonical write stands, a
    subtree-reindex retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = archive.collections.save(collection, expected_version, changed_by=changed_by)
    index_updated = _sync_index_subtree(archive, collection.ulid)
    _enqueue_mirror(collection.ulid)
    return SaveResult(version=new_version, index_updated=index_updated)


def _enqueue_mirror(ulid: str) -> None:
    """Enqueue the push of the Collection to the system of record (ADR 0020), AFTER the canonical
    write. Any failure is swallowed: the write stood, and the daily reconcile pushes what a lost job
    would have. A no-op when no system of record is configured."""
    try:
        enqueue_mirror_push(ulid)
    except Exception:  # noqa: BLE001 — queue down / mirror misconfigured -> the reconcile pushes it
        return


def _sync_index_subtree(archive: Archive, collection_ulid: str) -> bool:
    """Synchronously reindex the subtree; on ANY failure enqueue a reference retry job and report
    False (never re-raise — the canonical write already stood). Returns True on success."""
    try:
        index_subtree(archive.store, collection_ulid)
    except Exception:  # noqa: BLE001 — the canonical write stood; the sync index is best-effort, retry via queue
        _enqueue_reindex_subtree(collection_ulid)
        return False
    return True


def _enqueue_reindex_subtree(collection_ulid: str) -> None:
    """Enqueue a subtree reindex retry, swallowing failure — the periodic full rebuild heals it."""
    try:
        enqueue_reindex_subtree(collection_ulid)
    except Exception:  # noqa: BLE001 — ADR 0014 fail-open seam
        return
