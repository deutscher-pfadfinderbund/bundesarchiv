"""Collection write services."""

from bundesarchiv.app import after_write
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import CreateResult, SaveResult
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import ULID, Audience, Collection
from bundesarchiv.persistence.collections import StoredCollection
from bundesarchiv.persistence.errors import NotFound


def create_collection(
    archive: Archive,
    *,
    changed_by: str,
    name: str,
    parent_id: ULID | None = None,
    audience: Audience | None = None,
) -> CreateResult:
    if parent_id is not None and not _collection_exists(archive, parent_id):
        raise NotFound(f"parent collection {parent_id!r} does not exist")
    collection = Collection(
        ulid=identity.new_ulid(), name=name, parent_id=parent_id, audience=audience
    )
    new_version = archive.collections.save(collection, 0, changed_by=changed_by)  # first: v1
    index_updated = after_write.run(archive, after_write.CreatedCollection(collection))
    return CreateResult(ulid=collection.ulid, version=new_version, index_updated=index_updated)


def _collection_exists(archive: Archive, ulid: ULID) -> bool:
    try:
        archive.collections.load(ulid)
    except NotFound:
        return False
    return True


def save_collection(
    archive: Archive, stored: StoredCollection, collection: Collection, *, changed_by: str
) -> SaveResult:
    """Save ``collection`` over ``stored``, the copy it was edited from: the CAS at its version
    raises ``Conflict`` once another write landed, so ``stored`` is what the save replaces."""
    new_version = archive.collections.save(collection, stored.version, changed_by=changed_by)
    written = after_write.SavedCollection(stored.collection, collection)
    return SaveResult(version=new_version, index_updated=after_write.run(archive, written))
