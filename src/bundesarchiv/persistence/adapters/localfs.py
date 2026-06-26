"""Local-filesystem ObjectStore adapter — the canonical v1 backend (ADR 0005).

Atomic create-or-replace: write a temp sibling, fsync it, atomically rename it onto
the final path, then fsync the parent directory so the rename survives a crash. A
reader therefore sees the old bytes or the new bytes, never a partial write. Keys are
"/"-separated and map to paths under a root directory.
"""

import errno
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import BinaryIO

from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import is_reserved

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk for put_large


class LocalFsObjectStore:
    """Stores each blob as a file under `root`; key "a/b/c" → root/a/b/c."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Fail closed against traversal: app-internal keys are never absolute and
        # never carry "." or ".." segments. A reserved leading-dot segment (".lock",
        # ".tmp", ".snapshots") is a legitimate name, not traversal.
        segments = key.split("/")
        if not key or any(segment in ("", ".", "..") for segment in segments):
            raise ArchiveError(f"invalid key: {key!r}")
        return self._root.joinpath(*segments)

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError, IsADirectoryError:
            # A directory-prefix key (e.g. "art/1" when "art/1/README.md" exists)
            # names no blob — that is "absent", not a raw OSError past the port.
            raise NotFound(key) from None

    def write_atomic(self, key: str, data: bytes) -> None:
        def write(f: BinaryIO) -> None:
            f.write(data)

        self._commit(self._path(key), write)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        # `size` is a hint for multipart backends (S3/WebDAV); a streamed local write
        # has no use for it, but the ObjectStore port requires the parameter.
        def write(f: BinaryIO) -> None:
            while chunk := stream.read(_CHUNK):
                f.write(chunk)

        self._commit(self._path(key), write)

    def list(self, prefix: str = "") -> Iterable[str]:
        keys = (
            path.relative_to(self._root).as_posix()
            for path in self._root.rglob("*")
            if path.is_file()
        )
        return sorted(key for key in keys if key.startswith(prefix) and not is_reserved(key))

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_dir():
            return  # a directory-prefix key holds no blob — nothing to delete (no-op)
        path.unlink(missing_ok=True)

    def _commit(self, target: Path, write: Callable[[BinaryIO], None]) -> None:
        """Durably commit `write`'s output to `target`: temp → fsync → atomic
        rename → fsync parent dir. The temp sibling is reserved (".tmp-…"), so a
        crash that leaves it behind is invisible to `list()`."""
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".tmp-{os.getpid()}-{id(target)}-{target.name}"
        try:
            with tmp.open("wb") as f:
                write(f)
                f.flush()
                os.fsync(f.fileno())
            try:
                tmp.replace(target)
            except OSError as exc:
                if exc.errno == errno.EXDEV:
                    raise ArchiveError(f"cross-device rename refused (EXDEV): {target}") from exc
                raise
            self._fsync_dir(target.parent)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
