from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from bundesarchiv.domain.errors import BrokenCollectionTree, MisresolvedChain
from bundesarchiv.domain.models import Collection, Ulid


@dataclass(frozen=True, slots=True)
class ResolvedChain:
    """Leaf-first. Article-agnostic: binding it to an Article is `effective_audience`'s check."""

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
