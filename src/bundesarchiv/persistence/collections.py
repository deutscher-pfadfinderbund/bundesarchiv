"""CollectionRepository — the deep module for Collection persistence (ADR 0010/0013).

Key layout mirrors ArticleRepository:

    collections/<ulid>/README.md             the canonical commit point (front-matter + marker)
    collections/<ulid>/history/<version>.md  each replaced README

Migration (ADR 0013): a README written before versioning existed has no `version:` key; it loads
as version 0 and saves cleanly from there (its first save writes v1).

Callers depend only on this module; they never touch `ObjectStore` keys directly.
"""

from dataclasses import dataclass

from bundesarchiv.domain.models import Change, Collection, Ulid, Version
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence._layout import COLLECTIONS
from bundesarchiv.persistence._writer import StoredKey, commit, keys_in_save_order
from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


@dataclass(frozen=True, slots=True)
class StoredCollection:
    """A Collection as loaded, paired with the version to pass to the next `save` and that
    version's change record — mirrors ArticleRepository's `Stored`."""

    collection: Collection
    version: Version
    change: Change | None


class CollectionRepository:
    """Loads and saves Collections as the canonical collections/<ulid>/ tree
    on an `ObjectStore`."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def load(self, ulid: Ulid) -> StoredCollection:
        """Return the Collection for `ulid` with its stored version and change record. Raises
        `NotFound` if absent."""
        try:
            text = self._store.read(COLLECTIONS.readme_key(ulid)).decode("utf-8")
        except NotFound:
            raise NotFound(ulid) from None
        collection, version, change = collection_readme.decode_collection(text, ulid=ulid)
        return StoredCollection(collection, version, change)

    def save(
        self, collection: Collection, expected_version: Version, *, changed_by: str
    ) -> Version:
        """Optimistically create-or-replace the Collection's README, by `changed_by`, returning the
        new version. Raises `Conflict` (writing nothing) if the store's version no longer matches
        `expected_version` — a concurrent write won."""
        ulid = collection.ulid
        return commit(
            self._store,
            COLLECTIONS.folder(ulid),
            expected_version,
            changed_by=changed_by,
            version_of=lambda text: collection_readme.decode_collection(text, ulid=ulid)[1],
            render=lambda version, change: collection_readme.encode_collection(
                collection, version, change
            ),
        )

    def load_all(self) -> tuple[Collection, ...]:
        """Return every saved Collection (for tree assembly / rebuild).

        Returns plain `Collection`s, NOT `StoredCollection`s: tree assembly and the
        indexer resolve chains and audience from Collection fields alone — they never
        write, so they need no versions. Callers that intend to `save` must `load` the
        one Collection to get its version."""
        return tuple(self.load(ulid).collection for ulid in self.list_ulids())

    def list_ulids(self) -> list[Ulid]:
        """The ulid of every saved Collection, none of them read."""
        return COLLECTIONS.list_ulids(self._store)

    def keys_for(self, ulid: Ulid) -> list[StoredKey]:
        """The keys of the Collection's folder in the order a save writes them: history, the README
        last (ADR 0020 push order). A README that does not decode is not `readable`. An absent
        Collection yields ``[]``."""
        return keys_in_save_order(
            self._store, COLLECTIONS.folder(ulid), {}, readable=self._decodes(ulid)
        )

    def _decodes(self, ulid: Ulid) -> bool:
        try:
            self.load(ulid)
        except NotFound:
            return True
        except ArchiveError, UnicodeDecodeError:
            return False
        return True
