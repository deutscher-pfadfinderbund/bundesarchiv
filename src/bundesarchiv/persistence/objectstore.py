"""The ObjectStore port: a minimal blob interface defined to the WebDAV/S3
lowest common denominator — no append, no rename, no OS-level lock (ADR 0005).

Backends vary (in-memory, local filesystem, WebDAV, S3); every adapter satisfies
this Protocol and the conformance suite. Keys are "/"-separated paths.
"""

from collections.abc import Iterable
from typing import BinaryIO, Protocol, runtime_checkable

# A key is "reserved" if any "/"-segment starts with a dot. Reserved keys are the
# storage protocol's internal namespace: temp-write scratch (".tmp/…"), per-Article
# lock objects ("…/.lock"), and snapshot history ("…/.snapshots/…"). They are real,
# durable keys — `read`/`write_atomic`/`exists` see them and address them by direct
# key — but they are EXCLUDED from `list()`, so a walk sees only live content.
_RESERVED_SEGMENT_PREFIX = "."


def is_reserved(key: str) -> bool:
    """True if `key` is in the reserved internal namespace (excluded from `list()`)."""
    return any(segment.startswith(_RESERVED_SEGMENT_PREFIX) for segment in key.split("/"))


@runtime_checkable
class ObjectStore(Protocol):
    """A blob store keyed by "/"-separated paths."""

    def read(self, key: str) -> bytes:
        """Return the bytes at `key`. Raise `NotFound` if absent."""
        ...

    def write_atomic(self, key: str, data: bytes) -> None:
        """Create-or-replace `key` atomically — a concurrent reader sees the old
        bytes or the new bytes, never a partial write."""
        ...

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        """Stream a large object into `key`, with the same all-or-nothing finalize
        as `write_atomic`. `size` is the expected byte length (a hint for backends
        that need it, e.g. multipart upload)."""
        ...

    def list(self, prefix: str = "") -> Iterable[str]:
        """Keys beginning with `prefix`, in lexicographic order, excluding reserved
        internal keys (temp/lock/snapshots). `Iterable`, not `Iterator`: an adapter
        may return a materialized, sorted list (the natural local-FS/WebDAV shape)."""
        ...

    def exists(self, key: str) -> bool:
        """True if `key` exists (reserved keys included)."""
        ...

    def delete(self, key: str) -> None:
        """Delete `key`. Idempotent — deleting a missing key is a no-op."""
        ...
