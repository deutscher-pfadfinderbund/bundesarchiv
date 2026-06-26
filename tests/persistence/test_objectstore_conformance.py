"""Conformance suite: every ObjectStore adapter must pass these tests.

The `store` fixture is parametrized over every adapter — in-memory, local-FS, and
WebDAV (against a real in-process server) — so this one suite is the shared contract.

Scope note: ADR 0005's atomicity claims — a crash mid-write leaves
prior-object-or-nothing at the final key, and `put_large`'s finalize is
all-or-nothing — hold trivially for the in-memory fake (a single dict assignment),
so they are not stressed here. They are exercised for real by the SIGKILL crash test
in test_localfs.py, which kills a process mid-`put_large` (driving the same atomic
commit path both writes share) and inspects what survived on disk.
"""

import io
from pathlib import Path

import pytest

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


@pytest.fixture(params=["memory", "fs", "webdav"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    if request.param == "fs":
        return LocalFsObjectStore(tmp_path)
    if request.param == "webdav":
        # a real in-process WebDAV server (see conftest.webdav_store)
        webdav: ObjectStore = request.getfixturevalue("webdav_store")
        return webdav
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


def test_read_directory_prefix_key_raises_not_found(store: ObjectStore) -> None:
    # "art/1" names no blob even though "art/1/README.md" does — it is absent,
    # not a leaked backend error. (Pins memory and FS adapters to the same behavior.)
    store.write_atomic("art/1/README.md", b"body")
    with pytest.raises(NotFound):
        store.read("art/1")


def test_delete_directory_prefix_key_is_a_no_op(store: ObjectStore) -> None:
    # Deleting a directory-prefix key removes nothing and must not touch the blobs
    # nested under it.
    store.write_atomic("art/1/README.md", b"body")
    store.delete("art/1")
    assert store.read("art/1/README.md") == b"body"
