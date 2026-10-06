"""Conformance suite: every ObjectStore adapter must pass these tests.

The `store` fixture is parametrized over every adapter — in-memory, local-FS, and
WebDAV (against a real in-process server, and opt-in against a live one) — so this one
suite is the shared contract.

Scope note: ADR 0005's atomicity claims — a crash mid-write leaves
prior-object-or-nothing at the final key, and `create_large`'s finalize is
all-or-nothing — hold trivially for the in-memory fake (a single dict assignment),
so the crash half is not stressed here. The SIGKILL crash tests in test_localfs.py
exercise it for real: a process killed mid-stream in `create_large` leaves no key, and
one killed at the rename of a `write_atomic` replace leaves the prior value. What a
concurrent reader may see (old or new bytes, or NotFound before a create lands, never
a prefix) is raced here against both `write_atomic` and `create_large`.
"""

import io
import os
import threading
import time
import tracemalloc
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

import pytest

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, Busy, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore

# "live" joins only when LIVE_DAV_URL names a real server, so check and gate never reach one.
_ADAPTERS = ["memory", "fs", "webdav", *(["live"] if os.environ.get("LIVE_DAV_URL") else [])]
_WEBDAV_FIXTURES = {"webdav": "webdav_store", "live": "live_dav_store"}


@pytest.fixture(params=_ADAPTERS)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    if request.param == "fs":
        return LocalFsObjectStore(tmp_path)
    if request.param in _WEBDAV_FIXTURES:
        # a real WebDAV server: in-process, or the opt-in live one (see conftest)
        webdav: ObjectStore = request.getfixturevalue(_WEBDAV_FIXTURES[request.param])
        return webdav
    return InMemoryObjectStore()


type Create = Callable[[ObjectStore, str, bytes], str]


@pytest.fixture(params=["bytes", "streamed"])
def create(request: pytest.FixtureRequest) -> Create:
    """Each create-only write of the port: from bytes, and streamed."""
    if request.param == "streamed":
        return lambda store, key, data: store.create_large(key, io.BytesIO(data), len(data))
    return lambda store, key, data: store.create(key, data)


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


class _Trickle(io.BytesIO):
    """Hands its bytes out 64 KiB at a time with a pause, so a write stays open a while."""

    def read(self, size: int | None = -1) -> bytes:
        time.sleep(0.005)
        return super().read(-1 if size is None or size < 0 else min(size, 64 * 1024))


class _SourceFailed(Exception):
    pass


class _BreaksMidway(io.BytesIO):
    """Hands out its first 64 KiB, then fails, as a dying disk or client would."""

    def read(self, size: int | None = -1) -> bytes:
        if self.tell() or size is None or size < 0:
            raise _SourceFailed
        return super().read(min(size, 64 * 1024))


def test_a_reader_never_sees_a_create_in_progress(store: ObjectStore) -> None:
    data = bytes(range(256)) * 8 * 1024
    partial: list[int] = []
    with ThreadPoolExecutor(1) as pool:
        creating = pool.submit(store.create_large, "history/1.md", _Trickle(data), len(data))
        while not creating.done():
            try:
                read = store.read("history/1.md")
            except NotFound:
                continue
            if read != data:
                partial.append(len(read))
        creating.result()
    assert partial == [], "sizes of the partial reads"
    assert store.read("history/1.md") == data


def test_a_failed_create_leaves_nothing(store: ObjectStore) -> None:
    with pytest.raises(_SourceFailed):
        store.create_large("history/1.md", _BreaksMidway(bytes(1024 * 1024)), 1024 * 1024)
    assert (store.exists("history/1.md"), list(store.list())) == (False, [])
    store.create("history/1.md", b"retried")
    assert store.read("history/1.md") == b"retried"


def test_delete_prefix_removes_exactly_the_prefix(store: ObjectStore) -> None:
    doomed = ["articles/A/README.md", "articles/A/media/scan.pdf", "articles/A/.lock"]
    kept = ["articles/AB/README.md", "articles/B/README.md", "other/A/README.md"]
    for key in doomed + kept:
        store.write_atomic(key, b"x")
    store.delete_prefix("articles/A")
    assert list(store.list()) == kept
    assert not any(store.exists(key) for key in doomed)
    store.delete_prefix("articles/A")  # already gone: a no-op


def test_delete_prefix_through_a_blob_is_a_no_op(store: ObjectStore) -> None:
    store.write_atomic("articles/A/README.md", b"x")
    store.delete_prefix("articles/A/README.md/sub")
    assert store.read("articles/A/README.md") == b"x"


@pytest.mark.parametrize("prefix", ["articles", "articles/", "", "articles/../x", "a//b"])
def test_delete_prefix_refuses_a_short_or_invalid_prefix(store: ObjectStore, prefix: str) -> None:
    store.write_atomic("articles/A/README.md", b"x")
    with pytest.raises(ArchiveError):
        store.delete_prefix(prefix)
    assert list(store.list()) == ["articles/A/README.md"]


def test_list_by_prefix(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"1")
    store.write_atomic("art/2/README.md", b"2")
    store.write_atomic("other/x", b"3")
    assert set(store.list("art/")) == {"art/1/README.md", "art/2/README.md"}


def test_every_write_returns_the_version_the_listing_reports(store: ObjectStore) -> None:
    written = [
        ObjectEntry("art/1/a", 3, store.write_atomic("art/1/a", b"one")),
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
        store.write_atomic("k", b"one"),
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


def test_create_large_round_trip(store: ObjectStore) -> None:
    data = b"x" * 10_000
    store.create_large("media/big.bin", io.BytesIO(data), len(data))
    assert store.read("media/big.bin") == data


def test_open_stream_round_trip(store: ObjectStore) -> None:
    data = b"x" * 10_000
    store.create_large("media/big.bin", io.BytesIO(data), len(data))
    with store.open_stream("media/big.bin") as stream:
        assert stream.read() == data


def test_a_reader_never_sees_a_partial_write(store: ObjectStore) -> None:
    size = 2 * 1024 * 1024
    versions = [bytes([n]) * size for n in b"ab"]
    store.write_atomic("media/big.bin", versions[0])
    seen: list[bytes] = []

    def replace_repeatedly() -> None:
        for n in range(1, 9):
            store.write_atomic("media/big.bin", versions[n % 2])

    writer = threading.Thread(target=replace_repeatedly)
    writer.start()
    while writer.is_alive():
        seen.append(store.read("media/big.bin"))
    writer.join()
    assert all(read in versions for read in seen)


def test_a_streamed_read_does_not_hold_the_object_in_memory(store: ObjectStore) -> None:
    size = 16 * 1024 * 1024
    store.create_large("media/big.bin", io.BytesIO(bytes(size)), size)
    tracemalloc.start()
    try:
        with store.open_stream("media/big.bin") as stream:
            read = sum(len(chunk) for chunk in iter(lambda: stream.read(256 * 1024), b""))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert read == size
    assert peak < size // 4


def test_open_stream_missing_raises_not_found(store: ObjectStore) -> None:
    with pytest.raises(NotFound):
        store.open_stream("does/not/exist")


def test_open_stream_directory_prefix_key_raises_not_found(store: ObjectStore) -> None:
    store.write_atomic("art/1/README.md", b"body")
    with pytest.raises(NotFound), store.open_stream("art/1") as stream:
        pytest.fail(f"open_stream gave a stream of {stream.read(80)!r}")


def test_read_directory_prefix_key_raises_not_found(store: ObjectStore) -> None:
    # "art/1" names no blob even though "art/1/README.md" does — it is absent,
    # not a leaked backend error. (Pins memory and FS adapters to the same behavior.)
    store.write_atomic("art/1/README.md", b"body")
    with pytest.raises(NotFound):
        pytest.fail(f"read returned {store.read('art/1')[:80]!r}")


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
        store.create(bad, b"x")
    with pytest.raises(ArchiveError, match="invalid key"):
        store.create_large(bad, io.BytesIO(b"x"), 1)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.open_stream(bad)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.exists(bad)
    with pytest.raises(ArchiveError, match="invalid key"):
        store.delete(bad)
