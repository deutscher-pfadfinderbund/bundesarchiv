"""In-memory ObjectStore adapter: the simplest implementation, and the test fake
the ArticleRepository is exercised against (no disk).
"""

import io
import threading
from collections.abc import Iterator
from typing import BinaryIO

from bundesarchiv.persistence.errors import AlreadyExists, NotFound
from bundesarchiv.persistence.objectstore import is_reserved, validate_key


class InMemoryObjectStore:
    """Stores blobs in a dict. Writes are atomic (a single dict assignment);
    nothing is persisted across instances."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._create_lock = threading.Lock()

    def read(self, key: str) -> bytes:
        validate_key(key)
        try:
            return self._blobs[key]
        except KeyError:
            raise NotFound(key) from None

    def open_stream(self, key: str) -> BinaryIO:
        return io.BytesIO(self.read(key))

    def write_atomic(self, key: str, data: bytes) -> None:
        validate_key(key)
        self._blobs[key] = data

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        validate_key(key)
        self._blobs[key] = stream.read()

    def create(self, key: str, data: bytes) -> None:
        validate_key(key)
        with self._create_lock:
            if key in self._blobs:
                raise AlreadyExists(key)
            self._blobs[key] = data

    def create_large(self, key: str, stream: BinaryIO, size: int) -> None:
        self.create(key, stream.read())

    def list(self, prefix: str = "") -> Iterator[str]:
        for key in sorted(self._blobs):
            if key.startswith(prefix) and not is_reserved(key):
                yield key

    def exists(self, key: str) -> bool:
        validate_key(key)
        return key in self._blobs

    def delete(self, key: str) -> None:
        validate_key(key)
        self._blobs.pop(key, None)
