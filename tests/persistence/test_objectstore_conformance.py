"""Conformance suite: every ObjectStore adapter must pass these tests.

The `store` fixture provides the adapter under test. In-memory here; the local-FS
and WebDAV adapters will reuse this suite by parametrizing the fixture.

Scope note: the atomicity claims in ADR 0005 — a concurrent reader sees old-or-new
(never partial), a process killed mid-write leaves prior-object-or-nothing at the
final key, `put_large` finalize is all-or-nothing — hold trivially for the in-memory
fake (a single dict assignment) and so are not stressed here. They are exercised by
the local-FS crash-injection test added with `LocalFsObjectStore` (Part 1, step 5).
"""

import io

import pytest

from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


@pytest.fixture
def store() -> ObjectStore:
    return InMemoryObjectStore()


def test_write_then_read_round_trip(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"hello")
    assert store.read("art/1/README.md") == b"hello"


def test_read_missing_raises_not_found(store: ObjectStore) -> None:
    with pytest.raises(NotFound):
        store.read("does/not/exist")


def test_exists(store: ObjectStore) -> None:
    assert store.exists("k") is False
    store.write_atomic("k", b"x")
    assert store.exists("k") is True


def test_delete_is_idempotent(store: ObjectStore) -> None:
    store.write_atomic("k", b"x")
    store.delete("k")
    assert store.exists("k") is False
    store.delete("k")  # deleting a missing key is a no-op, not an error


def test_write_atomic_replaces_existing(store: ObjectStore) -> None:
    store.write_atomic("k", b"old")
    store.write_atomic("k", b"new")
    assert store.read("k") == b"new"


def test_list_by_prefix(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"1")
    store.write_atomic("art/2/README.md", b"2")
    store.write_atomic("other/x", b"3")
    assert set(store.list("art/")) == {"art/1/README.md", "art/2/README.md"}


def test_list_excludes_reserved_keys(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"1")
    store.write_atomic("art/1/.lock", b"lock")
    store.write_atomic(".tmp/scratch", b"tmp")
    assert set(store.list()) == {"art/1/README.md"}


def test_exists_includes_reserved_keys(store: ObjectStore) -> None:
    # The list/exists asymmetry: reserved keys are hidden from list() but remain
    # detectable via exists() — the per-Article lock object relies on this.
    store.write_atomic("art/1/.lock", b"lock")
    store.write_atomic(".tmp/scratch", b"tmp")
    assert store.exists("art/1/.lock") is True
    assert store.exists(".tmp/scratch") is True
    assert set(store.list()) == set()


def test_list_is_lexicographically_ordered(store: ObjectStore) -> None:
    for key in ("art/3", "art/1", "art/2"):
        store.write_atomic(key, b"x")
    assert list(store.list("art/")) == ["art/1", "art/2", "art/3"]


def test_put_large_round_trip(store: ObjectStore) -> None:
    data = b"x" * 10_000
    store.put_large("media/big.bin", io.BytesIO(data), len(data))
    assert store.read("media/big.bin") == data
