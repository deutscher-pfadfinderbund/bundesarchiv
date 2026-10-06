"""LocalFsObjectStore-specific tests: the atomicity guarantee the in-memory fake
cannot model — a process killed mid-write leaves prior-object-or-nothing at the
final key (ADR 0005). No mocking of the adapter: a real child process is SIGKILLed
mid-write and a fresh store inspects what actually landed on disk.

The general ObjectStore contract is covered by the parametrized conformance suite
(test_objectstore_conformance.py runs every adapter, including this one).
"""

import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore, _deletion_name
from bundesarchiv.persistence.errors import ArchiveError, NotFound


class _KillAfterFirstChunk:
    """A read-stream that yields one chunk, then SIGKILLs its own process on the
    next read — a deterministic hard crash partway through the write, with the real
    adapter doing the writing (this is test *input*, not a mock of the adapter)."""

    def __init__(self) -> None:
        self._sent = False

    def read(self, size: int = -1) -> bytes:
        if self._sent:
            os.kill(os.getpid(), signal.SIGKILL)
        self._sent = True
        return b"partial bytes that must never reach the final key"


def _kill_self(*_: object) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
@pytest.mark.parametrize("prior", [b"old", None], ids=["replace", "create"])
def test_sigkill_mid_write_keeps_prior_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior: bytes | None
) -> None:
    # A create-only key is never written again, so a partial one would stay for good.
    store = LocalFsObjectStore(tmp_path)
    if prior is not None:
        store.write_atomic("k", prior)

    pid = os.fork()
    if pid == 0:  # child: write through the real adapter, get SIGKILLed before the bytes land
        try:
            child = LocalFsObjectStore(tmp_path)
            if prior is None:
                child.create_large("k", cast(BinaryIO, _KillAfterFirstChunk()), 0)
            else:
                # write_atomic takes bytes, so die at the rename instead: the last instant
                # before the new bytes are placed, after anything a commit does first.
                monkeypatch.setattr(os, "replace", _kill_self)
                child.write_atomic("k", b"new bytes that must never replace the prior")
        finally:
            os._exit(1)  # unreachable if the SIGKILL fired, as it must
    _, status = os.waitpid(pid, 0)

    assert os.WIFSIGNALED(status), "child should have died from a signal, not exited"
    assert os.WTERMSIG(status) == signal.SIGKILL

    fresh = LocalFsObjectStore(tmp_path)
    # The real, adapter-emitted orphan temp (.tmp-…) is reserved, so it stays invisible.
    if prior is None:
        assert fresh.exists("k") is False
        assert set(fresh.list()) == set()
    else:
        assert fresh.read("k") == prior  # prior value intact — never the partial
        assert set(fresh.list()) == {"k"}


def test_successful_write_leaves_no_temp(tmp_path: Path) -> None:
    # A committed write (and overwrite) must clean up its temp sibling; orphans
    # must not accumulate on the canonical backend on the success path.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("art/1/x", b"v1")
    store.write_atomic("art/1/x", b"v2")
    store.create("art/1/y", b"v1")

    on_disk = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert on_disk == ["art/1/x", "art/1/y"]


def test_commit_fsyncs_every_directory_it_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Durability: a fresh deep key creates intermediate dirs; each must have its parent fsynced,
    # else a crash could lose a committed README despite the blob's own rename being durable.
    root = tmp_path / "root"
    store = LocalFsObjectStore(root)
    synced: list[Path] = []
    real = LocalFsObjectStore._fsync_dir

    def recording(directory: Path) -> None:
        synced.append(Path(directory))
        real(directory)

    monkeypatch.setattr(LocalFsObjectStore, "_fsync_dir", staticmethod(recording))
    store.write_atomic("articles/01J0/media/blob", b"data")

    for directory in (
        root,
        root / "articles",
        root / "articles/01J0",
        root / "articles/01J0/media",
    ):
        assert directory in synced, f"{directory} was not fsynced after creation"


def test_descend_through_a_file_key_is_not_found(tmp_path: Path) -> None:
    # A key whose intermediate component is an existing blob (ENOTDIR) names no blob -> NotFound,
    # matching the in-memory/WebDAV adapters (not a generic ArchiveError) so the port is uniform.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("art/1", b"i am a file")
    with pytest.raises(NotFound):
        store.read("art/1/extra")


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_read_unreadable_file_raises_archive_error(tmp_path: Path) -> None:
    # A real, broken backend (NO mocking): a key whose file is mode 000. read() must
    # surface this as ArchiveError, never let the raw PermissionError cross the port.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("secret", b"classified")
    target = tmp_path / "secret"
    target.chmod(0o000)
    try:
        with pytest.raises(ArchiveError):
            store.read("secret")
    finally:
        target.chmod(0o600)  # restore so pytest's tmp_path cleanup can remove it


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
def test_list_under_unreadable_dir_raises_not_under_reports(tmp_path: Path) -> None:
    # Fail closed: a walk that hits an unreadable directory must raise ArchiveError,
    # not silently drop that subtree's live content (no mocking — a real mode-000 dir).
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("a/k", b"x")
    store.write_atomic("a/sub/k", b"x")
    store.write_atomic("b/k", b"y")
    (tmp_path / "a").chmod(0o000)
    try:
        with pytest.raises(ArchiveError):
            store.list()
        with pytest.raises(ArchiveError):
            store.list("a/sub/")  # the prefix's folder itself cannot be looked at
        with pytest.raises(ArchiveError):
            store.exists("a/sub/k")  # unknown, not absent
        with pytest.raises(ArchiveError):
            store.delete("a/sub/k")
    finally:
        (tmp_path / "a").chmod(0o755)  # restore for cleanup


def test_delete_prefix_leaves_no_bytes_behind(tmp_path: Path) -> None:
    # The prefix is renamed out of sight before its removal; the renamed copy must go too.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("articles/A/media/scan.pdf", b"x")
    store.delete_prefix("articles/A")
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")] == ["articles"]


@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses file permissions")
@pytest.mark.parametrize(("locked", "mode"), [("a", 0o000), ("a/sub", 0o444)])
def test_delete_prefix_under_unreadable_dir_raises(tmp_path: Path, locked: str, mode: int) -> None:
    # A hard delete that cannot look must fail, not report success and leave the bytes.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("a/sub/x/k", b"x")
    (tmp_path / locked).chmod(mode)
    try:
        with pytest.raises(ArchiveError):
            store.delete_prefix("a/sub/x")
    finally:
        (tmp_path / locked).chmod(0o755)  # restore for cleanup


def _leftover(root: Path, name: str) -> Path:
    """What a delete_prefix that died after its rename leaves behind."""
    media = root / "articles" / name / "media"
    media.mkdir(parents=True)
    (media / "scan.pdf").write_bytes(b"x")
    return media.parent


@pytest.mark.parametrize("still_there", [True, False], ids=["folder-there", "folder-gone"])
def test_delete_prefix_removes_its_own_leftover(tmp_path: Path, still_there: bool) -> None:
    store = LocalFsObjectStore(tmp_path)
    _leftover(tmp_path, _deletion_name("A"))
    if still_there:
        store.write_atomic("articles/A/README.md", b"x")
    store.write_atomic("articles/B/README.md", b"kept")
    store.delete_prefix("articles/A")
    assert sorted(p.name for p in (tmp_path / "articles").iterdir()) == ["B"]


def test_delete_prefix_leaves_another_articles_leftover_alone(tmp_path: Path) -> None:
    # Deletes of different Articles run without a lock (_writer.py) and must not meet.
    store = LocalFsObjectStore(tmp_path)
    other = _leftover(tmp_path, _deletion_name("A"))
    store.write_atomic("articles/B/README.md", b"x")
    store.delete_prefix("articles/B")
    assert sorted(p.name for p in (tmp_path / "articles").iterdir()) == [_deletion_name("A")]
    assert (other / "media" / "scan.pdf").read_bytes() == b"x"


def test_concurrent_deletes_of_one_prefix_both_succeed(tmp_path: Path) -> None:
    store = LocalFsObjectStore(tmp_path)
    for n in range(300):
        store.write_atomic(f"articles/A/media/{n}.bin", b"x")
    start = threading.Barrier(2)

    def delete() -> None:
        start.wait()
        store.delete_prefix("articles/A")

    with ThreadPoolExecutor(2) as pool:
        for done in [pool.submit(delete) for _ in range(2)]:
            done.result()  # a NotFound or ArchiveError from either delete fails here
    assert list((tmp_path / "articles").iterdir()) == []


def test_delete_prefix_of_a_name_at_the_length_limit(tmp_path: Path) -> None:
    # A reserved name built from the segment itself would pass NAME_MAX for a 250-byte name.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic(f"articles/A/{'m' * 250}/scan.pdf", b"x")
    store.delete_prefix(f"articles/A/{'m' * 250}")
    assert list(store.list()) == []
