"""Local-filesystem ObjectStore adapter — the canonical v1 backend (ADR 0005).

Atomic create-or-replace: write a temp sibling, fsync it, atomically rename it onto
the final path, then fsync the parent directory so the rename survives a crash. A
reader therefore sees the old bytes or the new bytes, never a partial write. Keys are
"/"-separated and map to paths under a root directory.
"""

import errno
import os
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import is_reserved, validate_key

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk for put_large


class LocalFsObjectStore:
    """Stores each blob as a file under `root`; key "a/b/c" → root/a/b/c."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Every key-taking op routes through _path, so this is LocalFs's single
        # enforcement point for the port-level key contract (fail-closed traversal).
        validate_key(key)
        return self._root.joinpath(*key.split("/"))

    @contextmanager
    def _backend(self, key: str) -> Iterator[None]:
        """The single seam every filesystem operation passes through, so no raw
        `OSError` ever crosses the port (the local-FS analogue of WebDav's
        `_request`). A path that names no blob — missing (`FileNotFoundError`) or a
        directory-prefix key (`IsADirectoryError`) — is "absent" → `NotFound`; every
        other backend failure (permissions, ENOSPC, EXDEV, …) → `ArchiveError`."""
        try:
            yield
        except FileNotFoundError, IsADirectoryError:
            raise NotFound(key) from None
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise ArchiveError(f"cross-device rename refused (EXDEV): {key}") from exc
            raise ArchiveError(f"local-FS backend error on {key!r}: {exc}") from exc

    def read(self, key: str) -> bytes:
        with self._backend(key):
            return self._path(key).read_bytes()

    def write_atomic(self, key: str, data: bytes) -> None:
        def write(f: BinaryIO) -> None:
            f.write(data)

        with self._backend(key):
            self._commit(self._path(key), write)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        # `size` is a hint for multipart backends (S3/WebDAV); a streamed local write
        # has no use for it, but the ObjectStore port requires the parameter.
        def write(f: BinaryIO) -> None:
            while chunk := stream.read(_CHUNK):
                f.write(chunk)

        with self._backend(key):
            self._commit(self._path(key), write)

    def list(self, prefix: str = "") -> Iterable[str]:
        def _raise(exc: OSError) -> None:
            # Fail closed: an unreadable directory must error, not silently drop its
            # contents (rglob would swallow it and under-report live content).
            raise ArchiveError(f"local-FS list failed under {self._root}: {exc}") from exc

        keys = (
            Path(dirpath, name).relative_to(self._root).as_posix()
            for dirpath, _dirs, files in os.walk(self._root, onerror=_raise)
            for name in files
        )
        return sorted(key for key in keys if key.startswith(prefix) and not is_reserved(key))

    def exists(self, key: str) -> bool:
        with self._backend(key):
            return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        with self._backend(key):
            if path.is_dir():
                return  # a directory-prefix key holds no blob — nothing to delete (no-op)
            path.unlink(missing_ok=True)

    def _commit(self, target: Path, write: Callable[[BinaryIO], None]) -> None:
        """Durably commit `write`'s output to `target`: temp → fsync → atomic
        rename → fsync parent dir(s). The temp sibling is reserved (".tmp-…"), so a
        crash that leaves it behind is invisible to `list()`. Backend faults raised
        here (incl. EXDEV) are mapped to `ArchiveError` by the enclosing `_backend`."""
        created = _make_parents(target.parent)
        tmp = target.parent / f".tmp-{os.getpid()}-{id(target)}-{target.name}"
        try:
            with tmp.open("wb") as f:
                write(f)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(target)
            self._fsync_dir(target.parent)  # the renamed blob's entry, durable in its dir
            # Each directory we just created is only durable once ITS parent is fsynced too —
            # else a crash could lose a freshly-created articles/<ulid>/ despite the README
            # rename being durable inside it (the entry linking the new dir was never flushed).
            for directory in created:
                self._fsync_dir(directory.parent)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _make_parents(leaf: Path) -> list[Path]:
    """Create `leaf` and any missing ancestors; return the directories that were newly created
    (deepest-first), so the caller can fsync each one's parent for crash durability. Module-level
    so `list[Path]` resolves to the builtin, not LocalFsObjectStore.list."""
    created: list[Path] = []
    directory = leaf
    while not directory.exists() and directory != directory.parent:
        created.append(directory)
        directory = directory.parent
    leaf.mkdir(parents=True, exist_ok=True)
    return created
