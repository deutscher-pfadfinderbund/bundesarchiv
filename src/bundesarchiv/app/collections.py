"""Collection write service — the canonical-then-subtree-index shell (ADR 0013 + 0014).

A Collection audience or parent edit changes the effective audience of every descendant Article,
so after the canonical save we synchronously reindex the WHOLE subtree (``index_subtree``), not a
single row. Same failure contract as the Article services: a stale ``expected_version`` raises
``Conflict`` before any index work; an index failure leaves the canonical write standing, enqueues
a reference subtree-reindex job, and returns ``index_updated=False``.

``index_subtree`` and ``enqueue_reindex_subtree`` are module-level names so the service seam is
monkeypatchable in tests.
"""

from bundesarchiv.app.result import CreateResult, SaveResult
from bundesarchiv.app.tasks import enqueue_mirror_push, enqueue_reindex_subtree
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import Audience, Collection, Ulid, Version
from bundesarchiv.index.indexer import index_subtree
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


def create_collection(
    store: ObjectStore,
    *,
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
    if parent_id is not None and not _collection_exists(store, parent_id):
        raise NotFound(f"parent collection {parent_id!r} does not exist")
    collection = Collection(
        ulid=identity.new_ulid(), name=name, parent_id=parent_id, audience=audience
    )
    new_version = CollectionRepository(store).save(collection, 0)  # 0 = first save -> v1
    index_updated = _sync_index_subtree(store, collection.ulid)
    _enqueue_mirror(store, collection.ulid)
    return CreateResult(ulid=collection.ulid, version=new_version, index_updated=index_updated)


def _collection_exists(store: ObjectStore, ulid: Ulid) -> bool:
    """Is ``ulid`` a real saved Collection? A targeted load (1 read) rather than a full ``load_all``
    sweep — the caller maps a miss to the same refusal any invalid parent gets (no existence oracle)."""
    try:
        CollectionRepository(store).load(ulid)
    except NotFound:
        return False
    return True


def save_collection(
    store: ObjectStore, collection: Collection, expected_version: Version
) -> SaveResult:
    """Save ``collection`` (CAS at ``expected_version``) then synchronously reindex its whole
    subtree — an audience/parent edit moves every descendant Article's visibility. A stale version
    raises ``Conflict`` before any index work. On index failure the canonical write stands, a
    subtree-reindex retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = CollectionRepository(store).save(collection, expected_version)
    index_updated = _sync_index_subtree(store, collection.ulid)
    _enqueue_mirror(store, collection.ulid)
    return SaveResult(version=new_version, index_updated=index_updated)


def _enqueue_mirror(store: ObjectStore, ulid: str) -> None:
    """Enqueue a mirror_push for every canonical key of the Collection, AFTER the canonical write
    (Part 4.9). The mirror is a browse-only convenience — the replay is async and out-of-band, so an
    enqueue failure must never fail the request (the periodic reconcile heals mirror lag). A no-op
    when no mirror is configured."""
    try:
        for key in CollectionRepository(store).keys_for(ulid):
            enqueue_mirror_push(key)
    except Exception:  # queue down / mirror misconfigured -> mirror lag heals at the next reconcile
        return


def _sync_index_subtree(store: ObjectStore, collection_ulid: str) -> bool:
    """Synchronously reindex the subtree; on ANY failure enqueue a reference retry job and report
    False (never re-raise — the canonical write already stood). Returns True on success."""
    try:
        index_subtree(store, collection_ulid)
    except Exception:  # the canonical write stood; the sync index is best-effort, retry via queue
        enqueue_reindex_subtree(collection_ulid)
        return False
    return True
