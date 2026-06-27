"""Collection-tree resolution — an Article's owning Collection chain, fail-closed.

`resolve_chain` builds the chain; `ResolvedChain` is the value object that *owns* the
structural invariant (non-empty, parent-linked leaf→root, root-terminated). resolve_chain
is its sole sanctioned producer; a hand-built malformed chain fails at construction.
"""

import pytest

from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import BrokenCollectionTree, MisresolvedChain
from bundesarchiv.domain.models import Collection


def _tree(*collections: Collection) -> dict[str, Collection]:
    return {c.ulid: c for c in collections}


def test_resolve_chain_returns_leaf_to_root() -> None:
    root = Collection("root", "Archiv", parent_id=None)
    mid = Collection("mid", "Fotos", parent_id="root")
    leaf = Collection("leaf", "Zeltlager 1955", parent_id="mid")
    chain = resolve_chain("leaf", _tree(root, mid, leaf))
    assert isinstance(chain, ResolvedChain)
    assert chain.collections == (leaf, mid, root)  # leaf-first, root-last (pinned order)
    assert chain.leaf is leaf


def test_resolve_chain_of_a_root_is_just_itself() -> None:
    root = Collection("root", "Archiv", parent_id=None)
    assert resolve_chain("root", _tree(root)).collections == (root,)


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


# --- ResolvedChain: the structural invariant lives here, asserted at construction ---


def test_resolved_chain_rejects_an_empty_chain() -> None:
    # An empty chain has no owning Collection — unconstructable, not a silent default.
    with pytest.raises(MisresolvedChain):
        ResolvedChain(())


def test_resolved_chain_rejects_a_non_parent_linked_chain() -> None:
    # A spliced chain: chain[1] is not chain[0]'s parent. (Was a truncated/spliced-chain
    # case the resolver caught at runtime; now caught at construction.)
    leaf = Collection("leaf", "Fotos", parent_id="true-parent")
    unrelated = Collection("root", "Archiv", parent_id=None)
    with pytest.raises(MisresolvedChain):
        ResolvedChain((leaf, unrelated))


def test_resolved_chain_rejects_a_chain_not_terminated_at_a_root() -> None:
    # A truncated chain: the last element still names a parent, so it is not a root.
    leaf = Collection("leaf", "Fotos", parent_id="mid")
    with pytest.raises(MisresolvedChain):
        ResolvedChain((leaf,))


def test_resolved_chain_accepts_a_valid_parent_linked_root_terminated_chain() -> None:
    root = Collection("root", "Archiv", parent_id=None)
    leaf = Collection("leaf", "Fotos", parent_id="root")
    chain = ResolvedChain((leaf, root))
    assert chain.collections == (leaf, root)
    assert chain.leaf is leaf
