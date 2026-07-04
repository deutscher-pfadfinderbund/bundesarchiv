"""Collection write service — the canonical-then-subtree-index shell (ADR 0013 + 0014).

A Collection audience or parent edit changes the effective audience of every descendant Article,
so after the canonical save we synchronously reindex the WHOLE subtree (``index_subtree``), not a
single row. Same failure contract as the Article services: a stale ``expected_version`` raises
``Conflict`` before any index work; an index failure leaves the canonical write standing, enqueues
a reference subtree-reindex job, and returns ``index_updated=False``.

``index_subtree`` and ``enqueue_reindex_subtree`` are module-level names so the service seam is
monkeypatchable in tests.
"""

from bundesarchiv.app.result import SaveResult
from bundesarchiv.app.tasks import enqueue_reindex_subtree
from bundesarchiv.domain.models import Collection, Version
from bundesarchiv.index.indexer import index_subtree
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore


def save_collection(
    store: ObjectStore, collection: Collection, expected_version: Version
) -> SaveResult:
    """Save ``collection`` (CAS at ``expected_version``) then synchronously reindex its whole
    subtree — an audience/parent edit moves every descendant Article's visibility. A stale version
    raises ``Conflict`` before any index work. On index failure the canonical write stands, a
    subtree-reindex retry job is enqueued, and ``index_updated=False`` is returned (ADR 0014)."""
    new_version = CollectionRepository(store).save(collection, expected_version)
    index_updated = _sync_index_subtree(store, collection.ulid)
    return SaveResult(version=new_version, index_updated=index_updated)


def _sync_index_subtree(store: ObjectStore, collection_ulid: str) -> bool:
    """Synchronously reindex the subtree; on ANY failure enqueue a reference retry job and report
    False (never re-raise — the canonical write already stood). Returns True on success."""
    try:
        index_subtree(store, collection_ulid)
    except Exception:  # the canonical write stood; the sync index is best-effort, retry via queue
        enqueue_reindex_subtree(collection_ulid)
        return False
    return True
