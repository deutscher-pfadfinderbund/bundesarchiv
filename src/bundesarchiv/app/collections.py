"""Collection write service — the canonical-then-subtree-index shell (ADR 0013 + 0014).

A Collection audience or parent edit changes the effective audience of every descendant Article,
so after the canonical save ``after_write.run`` reindexes the WHOLE subtree, not a single row. The
index holds no Collection name, and a new Collection holds no Articles, so a rename and a create
touch no row and skip the reindex. Same failure contract as the Article services: a stale
``expected_version`` raises ``Conflict`` before any index work; an index failure leaves the
canonical write standing and returns ``index_updated=False``.
"""

from dataclasses import replace

from bundesarchiv.app import after_write
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import CreateResult, SaveResult
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import Audience, Collection, Ulid, Version
from bundesarchiv.persistence.errors import ArchiveError, NotFound


def create_collection(
    archive: Archive,
    *,
    changed_by: str,
    name: str,
    parent_id: Ulid | None = None,
    audience: Audience | None = None,
) -> CreateResult:
    """Mint a NEW Collection (fresh ULID) and save it at version 0 → v1; nothing to reindex. A
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
    index_updated = after_write.run(archive, after_write.SavedCollection(collection.ulid))
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
    """Save ``collection`` (CAS at ``expected_version``), then synchronously reindex its whole
    subtree unless only the name changed — an audience/parent edit moves every descendant Article's
    visibility. A stale version raises ``Conflict`` before any index work. On index failure the
    canonical write stands, a subtree-reindex retry job is enqueued, and ``index_updated=False`` is
    returned (ADR 0014)."""
    moves = _moves_visibility(archive, collection, expected_version)
    new_version = archive.collections.save(collection, expected_version, changed_by=changed_by)
    written = after_write.MovedCollection if moves else after_write.SavedCollection
    index_updated = after_write.run(archive, written(collection.ulid))
    return SaveResult(version=new_version, index_updated=index_updated)


def _moves_visibility(archive: Archive, collection: Collection, expected_version: Version) -> bool:
    """Does saving ``collection`` change anything but the stored name? Read before the save: at
    ``expected_version`` the CAS refuses the save if another write lands in between. A stored
    Collection at any other version, or an unreadable one, counts as a change."""
    try:
        stored = archive.collections.load(collection.ulid)
    except ArchiveError:
        return True
    unchanged = replace(stored.collection, name=collection.name) == collection
    return stored.version != expected_version or not unchanged
