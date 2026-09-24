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
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

import pytest

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, Busy, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore


@pytest.fixture(params=["memory", "fs", "webdav"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    if request.param == "fs":
        return LocalFsObjectStore(tmp_path)
    if request.param == "webdav":
        # a real in-process WebDAV server (see conftest.webdav_store)
        webdav: ObjectStore = request.getfixturevalue("webdav_store")
        return webdav
    return InMemoryObjectStore()


type Create = Callable[[ObjectStore, str, bytes], str]


@pytest.fixture(params=["bytes", "streamed"])
def create(request: pytest.FixtureRequest) -> Create:
    """Each create-only write of the port: from bytes, and streamed."""
    if request.param == "streamed":
        return lambda store, key, data: store.create_large(key, io.BytesIO(data), len(data))
    return lambda store, key, data: store.create(key, data)


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


def test_create_never_overwrites(store: ObjectStore, create: Create) -> None:
    create(store, "history/1.md", b"first")
    store.write_atomic("history/2.md", b"written")
    with pytest.raises(AlreadyExists):
        create(store, "history/1.md", b"second")
    with pytest.raises(AlreadyExists):
        create(store, "history/2.md", b"second")
    assert store.read("history/1.md") == b"first"
    assert store.read("history/2.md") == b"written"


def test_of_concurrent_creates_of_one_key_exactly_one_wins(
    store: ObjectStore, create: Create
) -> None:
    contenders = 8
    start = threading.Barrier(contenders)

    def contend(n: int) -> tuple[bytes, str] | None:
        data = f"writer {n}".encode()
        start.wait()
        try:
            return data, create(store, "history/1.md", data)
        except AlreadyExists, Busy:
            return None

    with ThreadPoolExecutor(contenders) as pool:
        winners = [won for won in pool.map(contend, range(contenders)) if won is not None]
    stored = store.read("history/1.md")
    assert [data for data, _ in winners] == [stored], f"winners (bytes, version): {winners}"


class _SourceFailed(Exception):
    pass


class _BreaksMidway(io.BytesIO):
    """Hands out its first 64 KiB, then fails, as a dying disk or client would."""

    def read(self, size: int | None = -1) -> bytes:
        if self.tell() or size is None or size < 0:
            raise _SourceFailed
        return super().read(min(size, 64 * 1024))


def test_a_failed_create_leaves_nothing(store: ObjectStore) -> None:
    with pytest.raises(_SourceFailed):
        store.create_large("history/1.md", _BreaksMidway(bytes(1024 * 1024)), 1024 * 1024)
    assert (store.exists("history/1.md"), list(store.list())) == (False, [])
    store.create("history/1.md", b"retried")
    assert store.read("history/1.md") == b"retried"


def test_list_by_prefix(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"1")
    store.write_atomic("art/2/README.md", b"2")
    store.write_atomic("other/x", b"3")
    assert set(store.list("art/")) == {"art/1/README.md", "art/2/README.md"}


def test_every_write_returns_the_version_the_listing_reports(store: ObjectStore) -> None:
    written = [
        ObjectEntry("art/1/a", 3, store.write_atomic("art/1/a", b"one")),
        ObjectEntry("art/1/b", 4, store.put_large("art/1/b", io.BytesIO(b"four"), 4)),
        ObjectEntry("art/10/c", 5, store.create("art/10/c", b"fives")),
        ObjectEntry("art/1/d", 6, store.create_large("art/1/d", io.BytesIO(b"sixsix"), 6)),
    ]
    store.write_atomic("art/2/e", b"elsewhere")
    store.write_atomic("art/1/.lock", b"reserved")
    assert list(store.list_entries("art/1")) == sorted(written, key=lambda entry: entry.key)


def test_the_version_changes_whenever_the_bytes_change(store: ObjectStore) -> None:
    versions = [
        store.write_atomic("k", b"one"),
        store.write_atomic("k", b"two"),
        store.put_large("k", io.BytesIO(b"one"), 3),
        store.write_atomic("k", b"six"),
    ]
    assert [before != after for before, after in pairwise(versions)] == [True] * 3, versions


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


def test_open_stream_round_trip(store: ObjectStore) -> None:
    data = b"x" * 10_000
    store.put_large("media/big.bin", io.BytesIO(data), len(data))
    with store.open_stream("media/big.bin") as stream:
        assert stream.read() == data


def test_a_reader_never_sees_a_partial_write(store: ObjectStore) -> None:
    size = 2 * 1024 * 1024
    versions = [bytes([n]) * size for n in b"ab"]
    store.write_atomic("media/big.bin", versions[0])
    seen: list[bytes] = []

    def replace_repeatedly() -> None:
        for n in range(1, 9):
            store.put_large("media/big.bin", io.BytesIO(versions[n % 2]), size)

    writer = threading.Thread(target=replace_repeatedly)
    writer.start()
    while writer.is_alive():
        seen.append(store.read("media/big.bin"))
    writer.join()
    assert all(read in versions for read in seen)


def test_open_stream_missing_raises_not_found(store: ObjectStore) -> None:
    with pytest.raises(NotFound):
        store.open_stream("does/not/exist")


def test_open_stream_directory_prefix_key_raises_not_found(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"body")
    with pytest.raises(NotFound):
        store.open_stream("art/1")


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


@pytest.mark.parametrize(
    "bad",
    ["", ".", "..", "a/../b", "a//b", "/x", "x/", "a\x00b", "a\tb", "a\x7fb"],
)
def test_invalid_keys_are_rejected(store: ObjectStore, bad: str) -> None:
    # Key validity (fail-closed traversal safety + no control chars) is a port
    # contract EVERY key-taking op of EVERY adapter enforces — not a rule only the
    # local-FS adapter happens to apply. NUL/control chars matter because they would
    # otherwise leak a raw ValueError from pathlib or be silently stored by the fake.
    with pytest.raises(ArchiveError, match="invalid key"):
        store.read(bad)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.write_atomic(bad, b"x")
    with pytest.raises(ArchiveError, match="invalid key"):
        store.put_large(bad, io.BytesIO(b"x"), 1)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.create(bad, b"x")
    with pytest.raises(ArchiveError, match="invalid key"):
        store.create_large(bad, io.BytesIO(b"x"), 1)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.open_stream(bad)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.exists(bad)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.delete(bad)
