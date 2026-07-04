"""CollectionRepository — the deep module for Collection persistence (ADR 0010/0013).

Key layout mirrors ArticleRepository:

    collections/<ulid>/README.md    the canonical commit point (front-matter + marker)

Collections have no media and no change log — their README is simpler than an
Article's — but they DO carry a `version` (ADR 0013): a lost collection edit is an
access-control change (Collections carry audience), so `save` is optimistic, not
last-write-wins. The version lives in the README front matter (the source of truth for
CAS); a stale `expected_version` raises the shared `Conflict`. The check-then-write
critical section is serialized by the ONE process-wide `WRITER_LOCK` shared with
ArticleRepository (both write the same store) — see `persistence/_writer.py`.

Migration (ADR 0013): a README written before versioning existed has no `version:`
key; it loads as version 0 and saves cleanly from there (its first save writes v1).

Callers depend only on this module; they never touch `ObjectStore` keys directly.
"""

from dataclasses import dataclass

from bundesarchiv.domain.models import Collection, Ulid, Version
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence._writer import WRITER_LOCK
from bundesarchiv.persistence.errors import Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


@dataclass(frozen=True, slots=True)
class StoredCollection:
    """A Collection as loaded, paired with the version to pass to the next `save`.
    (`load` returns this rather than a bare Collection so optimistic concurrency works —
    mirrors ArticleRepository's `Stored`.)"""

    collection: Collection
    version: Version


class CollectionRepository:
    """Loads and saves Collections as the canonical collections/<ulid>/ tree
    on an `ObjectStore`."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def load(self, ulid: Ulid) -> StoredCollection:
        """Return the Collection for `ulid` paired with its stored version. Raises
        `NotFound` if absent."""
        try:
            text = self._store.read(_readme_key(ulid)).decode("utf-8")
        except NotFound:
            raise NotFound(ulid) from None
        collection, version = collection_readme.decode_collection(text, ulid=ulid)
        return StoredCollection(collection, version)

    def save(self, collection: Collection, expected_version: Version) -> Version:
        """Optimistically create-or-replace the Collection's README, returning the new
        version. Raises `Conflict` (writing nothing) if the store's version no longer
        matches `expected_version` — a concurrent write won.

        The current-version read → compare → commit write is the critical section held
        under the shared `WRITER_LOCK` (ADR 0013); the port has no CAS, so the lock is
        what makes check-then-write atomic within the single app process."""
        with WRITER_LOCK:
            current = self._current_version(collection.ulid)
            if current != expected_version:
                raise Conflict(
                    f"{collection.ulid}: expected version {expected_version}, store has {current}"
                )
            new_version = current + 1
            self._store.write_atomic(
                _readme_key(collection.ulid),
                collection_readme.encode_collection(collection, new_version).encode("utf-8"),
            )
        return new_version

    def load_all(self) -> tuple[Collection, ...]:
        """Return every saved Collection (for tree assembly / rebuild).

        Returns plain `Collection`s, NOT `StoredCollection`s: tree assembly and the
        indexer resolve chains and audience from Collection fields alone — they never
        write, so they need no versions. Callers that intend to `save` must `load` the
        one Collection to get its version."""
        return tuple(
            self.load(ulid).collection
            for key in self._store.list("collections/")
            if (ulid := _ulid_of_readme(key)) is not None
        )

    def hard_delete(self, ulid: Ulid) -> None:
        """Delete the Collection's README. A no-op if the Collection is absent."""
        keys = list(self._store.list(f"collections/{ulid}/"))
        for key in keys:
            self._store.delete(key)

    def _current_version(self, ulid: Ulid) -> Version:
        try:
            text = self._store.read(_readme_key(ulid)).decode("utf-8")
        except NotFound:
            return 0
        _collection, version = collection_readme.decode_collection(text, ulid=ulid)
        return version


# --- key scheme ------------------------------------------------------------------


def _readme_key(ulid: Ulid) -> str:
    return f"collections/{ulid}/README.md"


def _ulid_of_readme(key: str) -> Ulid | None:
    # "collections/<ulid>/README.md" -> "<ulid>"; anything else -> None
    parts = key.split("/")
    if len(parts) == 3 and parts[0] == "collections" and parts[2] == "README.md":
        return parts[1]
    return None
