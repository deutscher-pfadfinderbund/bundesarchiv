"""LocalFsObjectStore-specific tests: the atomicity guarantee the in-memory fake
cannot model — a process killed mid-write leaves prior-object-or-nothing at the
final key (ADR 0005). No mocking of the adapter: a real child process is SIGKILLed
mid-write and a fresh store inspects what actually landed on disk.

The general ObjectStore contract is covered by the parametrized conformance suite
(test_objectstore_conformance.py runs every adapter, including this one).
"""

import os
import signal
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
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


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_sigkill_mid_write_keeps_prior_value(tmp_path: Path) -> None:
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("k", b"old")

    pid = os.fork()
    if pid == 0:  # child: write through the real adapter, get SIGKILLed before rename
        try:
            LocalFsObjectStore(tmp_path).put_large(
                "k", cast(BinaryIO, _KillAfterFirstChunk()), size=0
            )
        finally:
            os._exit(1)  # unreachable if the SIGKILL fired, as it must
    _, status = os.waitpid(pid, 0)

    assert os.WIFSIGNALED(status), "child should have died from a signal, not exited"
    assert os.WTERMSIG(status) == signal.SIGKILL

    fresh = LocalFsObjectStore(tmp_path)
    assert fresh.read("k") == b"old"  # prior value intact — never the partial
    # The real, adapter-emitted orphan temp (.tmp-…) is reserved, so it stays
    # invisible while the live key still lists: a real-shaped orphan coexisting
    # with real content.
    assert set(fresh.list()) == {"k"}


def test_successful_write_leaves_no_temp(tmp_path: Path) -> None:
    # A committed write (and overwrite) must clean up its temp sibling; orphans
    # must not accumulate on the canonical backend on the success path.
    store = LocalFsObjectStore(tmp_path)
    store.write_atomic("art/1/x", b"v1")
    store.write_atomic("art/1/x", b"v2")

    on_disk = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert on_disk == ["art/1/x"]


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
    store.write_atomic("b/k", b"y")
    (tmp_path / "a").chmod(0o000)
    try:
        with pytest.raises(ArchiveError):
            store.list()
    finally:
        (tmp_path / "a").chmod(0o755)  # restore for cleanup
