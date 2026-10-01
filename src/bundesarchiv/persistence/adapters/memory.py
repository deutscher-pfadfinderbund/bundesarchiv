"""In-memory ObjectStore adapter: the simplest implementation, and the test fake
the ArticleRepository is exercised against (no disk).
"""

import io
import itertools
import threading
from collections.abc import Iterable
from typing import BinaryIO

from bundesarchiv.persistence.errors import AlreadyExists, NotFound
from bundesarchiv.persistence.objectstore import (
    ObjectEntry,
    ObjectStore,
    is_reserved,
    validate_key,
    validate_prefix,
)


class InMemoryObjectStore(ObjectStore):
    """Stores blobs in a dict. Writes are atomic (a single dict assignment);
    nothing is persisted across instances. A version is a per-store write counter."""

    def __init__(self) -> None:
        self._blobs: dict[str, tuple[bytes, str]] = {}
        self._writes = itertools.count(1)
        self._create_lock = threading.Lock()

    def read(self, key: str) -> bytes:
        validate_key(key)
        try:
            return self._blobs[key][0]
        except KeyError:
            raise NotFound(key) from None

    def open_stream(self, key: str) -> BinaryIO:
        return io.BytesIO(self.read(key))

    def write_atomic(self, key: str, data: bytes) -> str:
        validate_key(key)
        return self._store(key, data)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> str:
        return self.write_atomic(key, stream.read())

    def create(self, key: str, data: bytes) -> str:
        validate_key(key)
        with self._create_lock:
            if key in self._blobs:
                raise AlreadyExists(key)
            return self._store(key, data)

    def create_large(self, key: str, stream: BinaryIO, size: int) -> str:
        return self.create(key, stream.read())

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        return [
            ObjectEntry(key, len(data), version)
            for key, (data, version) in sorted(self._blobs.items())
            if key.startswith(prefix) and not is_reserved(key)
        ]

    def exists(self, key: str) -> bool:
        validate_key(key)
        return key in self._blobs

    def delete(self, key: str) -> None:
        validate_key(key)
        self._blobs.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        validate_prefix(prefix)
        for key in [key for key in self._blobs if key.startswith(f"{prefix}/")]:
            del self._blobs[key]

    def _store(self, key: str, data: bytes) -> str:
        version = str(next(self._writes))
        self._blobs[key] = (data, version)
        return version
