"""Local-filesystem ObjectStore adapter — the canonical v1 backend (ADR 0005).

Every write goes to a temp sibling and is fsynced, then placed on the final path in one
step, then the parent directory is fsynced so the placement survives a crash. A reader
therefore sees the old bytes or the new bytes, never a partial write. A replace places
with `rename`; a create with `link`, which refuses an existing target (POSIX `link(2)`:
`EEXIST`, never replaces — relied on for macOS and Linux) and so gives exactly one winner.
Keys are "/"-separated and map to paths under a root directory.

Version token: `<inode>-<mtime ns>-<size>`, read with `fstat` from the written file, so it
equals what a later listing stats. Every write lands a new file while the old one still
exists, so a write's token always differs from the token it replaced. A token can recur
only if a later write gets back a freed inode within one timestamp tick at the same size.
"""

import errno
import os
import stat
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, is_reserved, validate_key

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

    def write_atomic(self, key: str, data: bytes) -> str:
        return self._commit(key, _bytes(data), replace=True)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> str:
        # `size` is a hint for multipart backends (S3/WebDAV); a streamed local write
        # has no use for it, but the ObjectStore port requires the parameter.
        return self._commit(key, _chunks(stream), replace=True)

    def create(self, key: str, data: bytes) -> str:
        return self._commit(key, _bytes(data), replace=False)

    def create_large(self, key: str, stream: BinaryIO, size: int) -> str:
        return self._commit(key, _chunks(stream), replace=False)

    def list(self, prefix: str = "") -> Iterable[str]:
        return [entry.key for entry in self.list_entries(prefix)]

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        folder = prefix.rpartition("/")[0]
        try:
            top = self._path(folder) if folder else self._root
        except ArchiveError:
            return []  # no stored key has an invalid segment
        if is_reserved(folder):
            return []
        with self._backend(prefix):
            if not _is_dir(top):
                return []
        entries = (self._entry(path) for path in self._walk(top))
        return sorted(
            (entry for entry in entries if entry and entry.key.startswith(prefix)),
            key=lambda entry: entry.key,
        )

    def exists(self, key: str) -> bool:
        with self._backend(key):
            return _is_file(self._path(key))

    def delete(self, key: str) -> None:
        path = self._path(key)
        with self._backend(key):
            if _is_dir(path):
                return  # a directory-prefix key holds no blob — nothing to delete (no-op)
            path.unlink(missing_ok=True)

    def _walk(self, top: Path) -> Iterator[Path]:
        def _raise(exc: OSError) -> None:
            # Fail closed: an unreadable directory must error, not silently drop its
            # contents (rglob would swallow it and under-report live content).
            raise ArchiveError(f"local-FS list failed under {top}: {exc}") from exc

        for dirpath, dirs, files in os.walk(top, onerror=_raise):
            dirs[:] = [name for name in dirs if not is_reserved(name)]
            yield from (Path(dirpath, name) for name in files if not is_reserved(name))

    def _entry(self, path: Path) -> ObjectEntry | None:
        try:
            result = _stat(path)
        except OSError as exc:
            raise ArchiveError(f"local-FS stat failed on {path}: {exc}") from exc
        if result is None:
            return None  # deleted since the walk saw it
        return ObjectEntry(
            path.relative_to(self._root).as_posix(), result.st_size, _version(result)
        )

    def _commit(self, key: str, write: Callable[[BinaryIO], None], *, replace: bool) -> str:
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
                    version = _version(os.fstat(f.fileno()))
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
        return version

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _version(result: os.stat_result) -> str:
    return f"{result.st_ino}-{result.st_mtime_ns}-{result.st_size}"


def _stat(path: Path) -> os.stat_result | None:
    """The module's one way to ask whether something is at `path`: its stat, or None if nothing
    is. Unlike `Path.is_dir()`/`is_file()`, any other failure (EACCES on an ancestor) raises, for
    the enclosing `_backend` to map, so an unreadable folder never looks absent."""
    try:
        return path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None


def _is_dir(path: Path) -> bool:
    return (found := _stat(path)) is not None and stat.S_ISDIR(found.st_mode)


def _is_file(path: Path) -> bool:
    return (found := _stat(path)) is not None and stat.S_ISREG(found.st_mode)


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
    while _stat(directory) is None and directory != directory.parent:
        created.append(directory)
        directory = directory.parent
    leaf.mkdir(parents=True, exist_ok=True)
    return created
