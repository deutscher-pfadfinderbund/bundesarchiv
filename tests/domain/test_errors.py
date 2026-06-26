"""domain.errors — the pure-core exception hierarchy (its own base, not persistence's)."""

import pytest

from bundesarchiv.domain.errors import BrokenCollectionTree, DomainError


def test_domain_error_is_its_own_base_not_persistences() -> None:
    # The pure core must never depend on persistence; DomainError stands alone.
    from bundesarchiv.persistence.errors import ArchiveError

    assert not issubclass(DomainError, ArchiveError)
    assert issubclass(DomainError, Exception)


def test_broken_collection_tree_subclasses_domain_error() -> None:
    assert issubclass(BrokenCollectionTree, DomainError)


def test_broken_collection_tree_is_raisable_and_catchable() -> None:
    with pytest.raises(DomainError):
        raise BrokenCollectionTree("cycle detected")

    with pytest.raises(BrokenCollectionTree) as exc_info:
        raise BrokenCollectionTree("missing parent")
    assert "missing parent" in str(exc_info.value)
