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
