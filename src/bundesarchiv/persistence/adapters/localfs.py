"""Local-filesystem ObjectStore adapter — the canonical v1 backend (ADR 0005).

Every write goes to a temp sibling and is fsynced, then placed on the final path in one
step, then the parent directory is fsynced so the placement survives a crash. A reader
therefore sees the old bytes or the new bytes, never a partial write. A replace places
with `rename`; a create with `link`, which refuses an existing target (POSIX `link(2)`:
`EEXIST`, never replaces — relied on for macOS and Linux) and so gives exactly one winner.
Keys are "/"-separated and map to paths under a root directory.
"""

import errno
import os
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, NotFound
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
        except FileNotFoundError, IsADirectoryError, NotADirectoryError:
            # No blob lives at this key: missing, a directory-prefix key, or a descend-through-
            # a-file key (ENOTDIR) — all "absent" -> NotFound, matching the in-memory/WebDAV
            # adapters so the port stays interchangeable.
            raise NotFound(key) from None
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise ArchiveError(f"cross-device rename refused (EXDEV): {key}") from exc
            raise ArchiveError(f"local-FS backend error on {key!r}: {exc}") from exc

    def read(self, key: str) -> bytes:
        with self._backend(key):
            return self._path(key).read_bytes()

    def open_stream(self, key: str) -> BinaryIO:
        with self._backend(key):
            return self._path(key).open("rb")

    def write_atomic(self, key: str, data: bytes) -> None:
        self._commit(key, _bytes(data), replace=True)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        # `size` is a hint for multipart backends (S3/WebDAV); a streamed local write
        # has no use for it, but the ObjectStore port requires the parameter.
        self._commit(key, _chunks(stream), replace=True)

    def create(self, key: str, data: bytes) -> None:
        self._commit(key, _bytes(data), replace=False)

    def create_large(self, key: str, stream: BinaryIO, size: int) -> None:
        self._commit(key, _chunks(stream), replace=False)

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

    def _commit(self, key: str, write: Callable[[BinaryIO], None], *, replace: bool) -> None:
        """Durably commit `write`'s output to `key`: temp → fsync → rename (`replace`) or
        link (create-only) → fsync parent dir(s). The temp sibling is reserved (".tmp-…"),
        so a crash that leaves it behind is invisible to `list()`."""
        with self._backend(key):
            target = self._path(key)
            created = _make_parents(target.parent)
            # Not named after the target: a 250-byte media name plus a prefix would pass NAME_MAX.
            tmp = target.parent / f".tmp-{uuid.uuid4().hex}"
            try:
                with tmp.open("wb") as f:
                    write(f)
                    f.flush()
                    os.fsync(f.fileno())
                if replace:
                    tmp.replace(target)
                else:
                    _link_new(key, tmp, target)
                self._fsync_dir(target.parent)  # the placed blob's entry, durable in its dir
                # Each directory we just created is only durable once ITS parent is fsynced
                # too — else a crash could lose a freshly-created articles/<ulid>/ despite the
                # README being durable inside it (the entry linking the new dir was never flushed).
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


def _bytes(data: bytes) -> Callable[[BinaryIO], None]:
    def write(f: BinaryIO) -> None:
        f.write(data)

    return write


def _chunks(stream: BinaryIO) -> Callable[[BinaryIO], None]:
    def write(f: BinaryIO) -> None:
        while chunk := stream.read(_CHUNK):
            f.write(chunk)

    return write


def _link_new(key: str, tmp: Path, target: Path) -> None:
    try:
        os.link(tmp, target)
    except FileExistsError:
        raise AlreadyExists(key) from None


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
