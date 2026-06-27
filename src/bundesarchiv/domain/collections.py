"""Collection-tree resolution (Part 2).

`resolve_chain` walks an Article's owning Collection chain — its Collection, then that
Collection's parent, up to the root — from an injected lookup (a mapping ULID → Collection,
passed in, never fetched here). It returns a `ResolvedChain`: the value object that *owns*
the structural invariant, so the leak-sensitive effective-Audience resolver can trust the
type rather than re-validate. Fail-closed: an unknown Collection, a missing parent, or a
cycle raises `BrokenCollectionTree` while building, before any `ResolvedChain` exists.

Order is leaf-first, root-last: the Article's own Collection at index 0, the root last.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from bundesarchiv.domain.errors import BrokenCollectionTree, MisresolvedChain
from bundesarchiv.domain.models import Collection, Ulid


@dataclass(frozen=True, slots=True)
class ResolvedChain:
    """An Article's owning Collection chain, leaf-first and root-last, proven well-formed at
    construction: non-empty, parent-linked (each element names the next as its parent), and
    terminated at a real root (`parent_id is None`). `resolve_chain` is the sole sanctioned
    producer; a malformed chain raises `MisresolvedChain` here rather than reaching the
    resolver. Article-agnostic: binding a chain to a specific Article (its leaf matching the
    Article's `collection_id`) is the resolver's check, not this type's — one chain is
    reusable across every Article in the same Collection.
    """

    collections: tuple[Collection, ...]

    def __post_init__(self) -> None:
        if not self.collections:
            raise MisresolvedChain("a resolved chain cannot be empty")
        for child, parent in pairwise(self.collections):
            if child.parent_id != parent.ulid:
                raise MisresolvedChain(
                    f"chain is not parent-linked: {child.ulid!r}.parent_id="
                    f"{child.parent_id!r} but next is {parent.ulid!r}"
                )
        last = self.collections[-1]
        if last.parent_id is not None:
            raise MisresolvedChain(
                f"chain does not terminate at a root: {last.ulid!r}.parent_id={last.parent_id!r}"
            )

    @property
    def leaf(self) -> Collection:
        """The Article's own Collection — the chain's first element."""
        return self.collections[0]


def resolve_chain(collection_id: Ulid, collections: Mapping[Ulid, Collection]) -> ResolvedChain:
    """The Collection chain from `collection_id` up to the root, leaf-first, as a validated
    `ResolvedChain`. Raises `BrokenCollectionTree` on a cycle, an unknown Collection, or a
    missing parent."""
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
    return ResolvedChain(tuple(chain))
