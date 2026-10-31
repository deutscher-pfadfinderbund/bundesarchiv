"""Chunked uploads staged on local disk, outside the archive, until the finish turns each into a
media file (ADR 0026). One folder per upload id: ``meta.json`` holds the ``Upload``, ``data`` the
bytes received so far, so its size is the offset. Every operation on one upload holds an exclusive
``flock`` on its ``data`` file, which serialises gunicorn's threads and the worker process alike.

Each operation names the upload by a ``Key``: a mismatch in any of its parts, a malformed id and an
upload swept or never created all read the same: absent.
"""

import contextlib
import fcntl
import functools
import json
import os
import re
import secrets
import shutil
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Protocol

from django.conf import settings

#: ADR 0026: an upload nobody touched for a day is abandoned.
STALE_AFTER_SECONDS = 24 * 60 * 60

_ID = re.compile(r"[0-9a-f]{32}")
#: The suffix of a folder ``create`` builds before it renames it to its id, which ``_ID`` refuses.
_PARTIAL = ".partial"
_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Upload:
    """``filename`` as the client named the file; ``add_media`` cleans it on the finish."""

    article: str
    owner: str
    filename: str
    media_type: str | None
    length: int


@dataclass(frozen=True, slots=True)
class Key:
    """An upload as its archivist addresses it: the id, and who asks on which Article."""

    upload_id: str
    owner: str
    article: str


@dataclass(frozen=True, slots=True)
class _Held:
    folder: Path
    upload: Upload
    data: BinaryIO


class Refused(Enum):
    ABSENT = "absent"
    OFFSET = "offset"
    TOO_LONG = "too long"


class Source(Protocol):
    def read(self, size: int, /) -> bytes: ...


class Staging:
    def __init__(self, root: Path) -> None:
        self._root = root

    @classmethod
    def configured(cls) -> Staging:
        return cls(Path(settings.BUNDESARCHIV_UPLOAD_STAGING_ROOT))

    def create(self, upload: Upload) -> str:
        """Stage an empty upload, whole or not at all; its id, unguessable."""
        upload_id = secrets.token_hex(16)
        partial = self._root / f"{upload_id}{_PARTIAL}"
        partial.mkdir(parents=True)
        (partial / "meta.json").write_text(json.dumps(asdict(upload)))
        (partial / "data").touch()
        partial.rename(self._root / upload_id)
        return upload_id

    def status(self, key: Key) -> tuple[Upload, int] | None:
        """The upload and its offset."""
        with self._held(key) as held:
            return None if held is None else (held.upload, _size(held.data))

    def append(self, key: Key, offset: int, source: Source, size: int) -> int | Refused:
        """Append ``size`` bytes read from ``source`` at ``offset``; the new offset. An offset
        that is not the current one, or bytes past the upload's length, write nothing. A source
        that ends early leaves what it gave, and the offset says how much."""
        with self._held(key) as held:
            if held is None:
                return Refused.ABSENT
            data = held.data
            if offset != _size(data):
                return Refused.OFFSET
            if offset + size > held.upload.length:
                return Refused.TOO_LONG
            data.seek(offset)
            remaining = size
            while remaining and (chunk := source.read(min(_CHUNK, remaining))):
                data.write(chunk)
                remaining -= len(chunk)
            data.flush()
            return data.tell()

    @contextmanager
    def claim(self, key: Key) -> Generator[tuple[Upload, BinaryIO, Callable[[], None]] | None]:
        """The complete upload, its bytes from the start and the act that removes it, held against
        every other operation until the block exits; an upload the block does not remove stays for
        the next claim. None for an incomplete upload."""
        with self._held(key) as held:
            if held is None or _size(held.data) != held.upload.length:
                yield None
                return
            held.data.seek(0)
            yield held.upload, held.data, functools.partial(shutil.rmtree, held.folder)

    def discard(self, key: Key) -> bool:
        """Remove the upload; False when it was absent."""
        with self._held(key) as held:
            if held is None:
                return False
            shutil.rmtree(held.folder)
            return True

    def sweep(self, older_than: float) -> None:
        """Remove every upload whose bytes last changed before ``older_than`` (a POSIX time), and
        what a ``create`` that crashed left before then. One in use right now is left for the next
        sweep."""
        if not self._root.is_dir():
            return
        for folder in self._root.iterdir():
            # A finish, discard or create may have moved the folder since the listing.
            with contextlib.suppress(FileNotFoundError):
                if _ID.fullmatch(folder.name):
                    _sweep_upload(folder, older_than)
                elif folder.name.endswith(_PARTIAL) and folder.stat().st_mtime < older_than:
                    shutil.rmtree(folder)

    @contextmanager
    def _held(self, key: Key) -> Generator[_Held | None]:
        """The upload's folder, record and locked data file, or None. The id is checked before it
        becomes a path."""
        if not _ID.fullmatch(key.upload_id):
            yield None
            return
        folder = self._root / key.upload_id
        try:
            data = (folder / "data").open("r+b")
        except FileNotFoundError:
            yield None
            return
        with data:
            fcntl.flock(data, fcntl.LOCK_EX)
            # A discard or sweep that held the lock first has unlinked the file this one opened.
            upload = (
                Upload(**json.loads((folder / "meta.json").read_text()))
                if os.fstat(data.fileno()).st_nlink
                else None
            )
            if upload is None or (upload.owner, upload.article) != (key.owner, key.article):
                yield None
            else:
                yield _Held(folder, upload, data)


def _sweep_upload(folder: Path, older_than: float) -> None:
    with (folder / "data").open("r+b") as data:
        try:
            fcntl.flock(data, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        stat = os.fstat(data.fileno())
        if stat.st_nlink and stat.st_mtime < older_than:
            shutil.rmtree(folder)


def _size(data: BinaryIO) -> int:
    return os.fstat(data.fileno()).st_size
