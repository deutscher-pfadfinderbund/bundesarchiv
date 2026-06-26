"""Collection-tree resolution (Part 2).

Resolves an Article's owning Collection chain — its Collection, then that Collection's
parent, up to the root — from an injected lookup (a mapping ULID → Collection, passed
in, never fetched here). Fail-closed: an unknown Collection, a missing parent, or a
cycle raises `BrokenCollectionTree` rather than walking a broken tree.

Order is leaf-first, root-last: the Article's own Collection at index 0, the root last.
"""

from collections.abc import Mapping

from bundesarchiv.domain.errors import BrokenCollectionTree
from bundesarchiv.domain.models import Collection, Ulid


def resolve_chain(
    collection_id: Ulid, collections: Mapping[Ulid, Collection]
) -> tuple[Collection, ...]:
    """The Collection chain from `collection_id` up to the root, leaf-first."""
    chain: list[Collection] = []
    seen: set[Ulid] = set()
    current: Ulid | None = collection_id
    while current is not None:
        if current in seen:
            raise BrokenCollectionTree(f"cycle in Collection tree at {current!r}")
        try:
            collection = collections[current]
        except KeyError:
            raise BrokenCollectionTree(f"unknown Collection {current!r}") from None
        chain.append(collection)
        seen.add(current)
        current = collection.parent_id
    return tuple(chain)
