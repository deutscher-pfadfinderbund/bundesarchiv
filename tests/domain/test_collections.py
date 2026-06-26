"""Collection-tree resolution — an Article's owning Collection chain, fail-closed."""

import pytest

from bundesarchiv.domain.collections import resolve_chain
from bundesarchiv.domain.errors import BrokenCollectionTree
from bundesarchiv.domain.models import Collection


def _tree(*collections: Collection) -> dict[str, Collection]:
    return {c.ulid: c for c in collections}


def test_resolve_chain_returns_leaf_to_root() -> None:
    root = Collection("root", "Archiv", parent_id=None)
    mid = Collection("mid", "Fotos", parent_id="root")
    leaf = Collection("leaf", "Zeltlager 1955", parent_id="mid")
    chain = resolve_chain("leaf", _tree(root, mid, leaf))
    assert chain == (leaf, mid, root)  # leaf-first, root-last (pinned order)


def test_resolve_chain_of_a_root_is_just_itself() -> None:
    root = Collection("root", "Archiv", parent_id=None)
    assert resolve_chain("root", _tree(root)) == (root,)


def test_unknown_collection_fails_closed() -> None:
    with pytest.raises(BrokenCollectionTree):
        resolve_chain("ghost", _tree(Collection("root", "Archiv", parent_id=None)))


def test_missing_parent_fails_closed() -> None:
    # leaf points at a parent that isn't in the lookup — must raise, not truncate.
    leaf = Collection("leaf", "Fotos", parent_id="gone")
    with pytest.raises(BrokenCollectionTree):
        resolve_chain("leaf", _tree(leaf))


def test_cycle_fails_closed() -> None:
    a = Collection("a", "A", parent_id="b")
    b = Collection("b", "B", parent_id="a")
    with pytest.raises(BrokenCollectionTree):
        resolve_chain("a", _tree(a, b))
