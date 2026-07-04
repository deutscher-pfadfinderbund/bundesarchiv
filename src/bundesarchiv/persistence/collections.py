"""CollectionRepository — the deep module for Collection persistence (ADR 0010).

Key layout mirrors ArticleRepository:

    collections/<ulid>/README.md    the canonical commit point (front-matter + marker)

Collections have no media, no versioning, and no change log — their README is
simpler than an Article's. `save` is last-write-wins under the single-writer
invariant (ADR 0002); a future optimistic-lock can be added here without
changing the caller interface.

Callers depend only on this module; they never touch `ObjectStore` keys directly.
"""

from bundesarchiv.domain.models import Collection, Ulid
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


class CollectionRepository:
    """Loads and saves Collections as the canonical collections/<ulid>/ tree
    on an `ObjectStore`."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def load(self, ulid: Ulid) -> Collection:
        """Return the Collection for `ulid`. Raises `NotFound` if absent."""
        try:
            text = self._store.read(_readme_key(ulid)).decode("utf-8")
        except NotFound:
            raise NotFound(ulid) from None
        return collection_readme.decode_collection(text, ulid=ulid)

    def save(self, collection: Collection) -> None:
        """Create-or-replace the Collection's README (last-write-wins)."""
        self._store.write_atomic(
            _readme_key(collection.ulid),
            collection_readme.encode_collection(collection).encode("utf-8"),
        )

    def load_all(self) -> tuple[Collection, ...]:
        """Return every saved Collection (for tree assembly / rebuild)."""
        return tuple(
            self.load(ulid)
            for key in self._store.list("collections/")
            if (ulid := _ulid_of_readme(key)) is not None
        )

    def hard_delete(self, ulid: Ulid) -> None:
        """Delete the Collection's README. A no-op if the Collection is absent."""
        keys = list(self._store.list(f"collections/{ulid}/"))
        for key in keys:
            self._store.delete(key)


# --- key scheme ------------------------------------------------------------------


def _readme_key(ulid: Ulid) -> str:
    return f"collections/{ulid}/README.md"


def _ulid_of_readme(key: str) -> Ulid | None:
    # "collections/<ulid>/README.md" -> "<ulid>"; anything else -> None
    parts = key.split("/")
    if len(parts) == 3 and parts[0] == "collections" and parts[2] == "README.md":
        return parts[1]
    return None
