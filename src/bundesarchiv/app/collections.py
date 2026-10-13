"""Collection write services: canonical CAS write, then ``after_write.run``, which reindexes the
whole subtree when the save moves any Article's visibility (an audience or parent edit). A rename
or a create touches no index row.
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
    """Mint a new Collection under ``parent_id`` (top-level when None) and save it at version 0. A
    missing parent raises ``NotFound`` (fail-closed). A new leaf holds no Articles, so its audience
    exposes nothing and nothing is reindexed."""
    if parent_id is not None and not _collection_exists(archive, parent_id):
        raise NotFound(f"parent collection {parent_id!r} does not exist")
    collection = Collection(
        ulid=identity.new_ulid(), name=name, parent_id=parent_id, audience=audience
    )
    new_version = archive.collections.save(collection, 0, changed_by=changed_by)  # first: v1
    index_updated = after_write.run(archive, after_write.SavedCollection(collection.ulid))
    return CreateResult(ulid=collection.ulid, version=new_version, index_updated=index_updated)


def _collection_exists(archive: Archive, ulid: Ulid) -> bool:
    try:
        archive.collections.load(ulid)
    except NotFound:
        return False
    return True


def save_collection(
    archive: Archive, collection: Collection, expected_version: Version, *, changed_by: str
) -> SaveResult:
    """Save ``collection`` at ``expected_version`` (a stale one raises ``Conflict``), then
    ``after_write.run``: a whole-subtree reindex unless only the name changed."""
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
