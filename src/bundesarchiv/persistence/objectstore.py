"""The ObjectStore port: a minimal blob interface defined to the WebDAV/S3
lowest common denominator — no append, no rename, no OS-level lock (ADR 0005).

Backends vary (in-memory, local filesystem, WebDAV, S3); every adapter satisfies
this Protocol and the conformance suite. Keys are "/"-separated paths.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from bundesarchiv.persistence.errors import ArchiveError

# A key is "reserved" if any "/"-segment starts with a dot. Reserved keys are the
# storage protocol's internal namespace: the local-FS adapter's temp siblings ("…/.tmp-<uuid>")
# and prefix-delete leftovers ("…/.deleted-<hash>"); ".lock" is reserved by ADR 0013 and unused.
# They are real, durable keys — `read`/`write_atomic`/`exists` see them and address them by direct
# key — but they are EXCLUDED from `list()`, so a walk sees only live content.
_RESERVED_SEGMENT_PREFIX = "."


def is_reserved(key: str) -> bool:
    """True if `key` is in the reserved internal namespace (excluded from `list()`)."""
    return any(segment.startswith(_RESERVED_SEGMENT_PREFIX) for segment in key.split("/"))


def validate_key(key: str) -> None:
    """Raise `ArchiveError` if `key` is not a valid object key — part of the port
    contract every adapter enforces on every key-taking operation.

    A key is "/"-separated and non-empty; no segment may be empty, "." or ".."
    (fail closed against path traversal), and no character may be a NUL or other
    ASCII control character (those provoke a raw ValueError from pathlib that would
    escape the port, and the in-memory fake would diverge by accepting them). A
    leading-dot reserved segment (".tmp-<uuid>") is valid.
    """
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        raise ArchiveError(f"invalid key: {key!r}")  # an empty key splits to [""], caught here
    if any(ch < " " or ch == "\x7f" for ch in key):
        raise ArchiveError(f"invalid key (control character): {key!r}")


def validate_prefix(prefix: str) -> None:
    """Raise `ArchiveError` unless `prefix` is a valid key of at least two segments, so no
    prefix delete can take a top-level folder or the whole root (ADR 0019)."""
    validate_key(prefix)
    if "/" not in prefix:
        raise ArchiveError(f"prefix too short to delete: {prefix!r}")


@dataclass(frozen=True, slots=True)
class ObjectEntry:
    """One listed object. `version` is an opaque token that changes whenever the object's bytes
    change and means nothing else; every write returns the token of what it wrote."""

    key: str
    size: int
    version: str


class ObjectStore(Protocol):
    """A blob store keyed by "/"-separated paths.

    Any operation may raise `Busy`: the backend refused under contention and the adapter's own
    bounded retries are spent. The call may be repeated later."""

    def read(self, key: str) -> bytes:
        """Return the bytes at `key`. Raise `NotFound` if absent."""
        ...

    def write_atomic(self, key: str, data: bytes) -> str:
        """Create-or-replace `key` atomically — a concurrent reader sees the old
        bytes or the new bytes, never a partial write."""
        ...

    def create(self, key: str, data: bytes) -> str:
        """Write `key` only if it does not exist yet, else raise `AlreadyExists` and write
        nothing. Of concurrent creates of one key exactly one succeeds. As atomic for readers
        as `write_atomic`."""
        ...

    def create_large(self, key: str, stream: BinaryIO, size: int) -> str:
        """`create`, streamed, with the same all-or-nothing finalize as `write_atomic`: a
        failed or aborted stream leaves no key. `size` is the expected byte length (a hint
        for backends that need it, e.g. multipart upload). An adapter that retries rewinds
        `stream` to where it stood at the call before each attempt; a non-seekable stream
        gets one attempt."""
        ...

    def open_stream(self, key: str) -> BinaryIO:
        """Return a readable binary stream over the object at `key`, which the caller
        closes. Raise `NotFound` if absent.

        The read counterpart of `create_large`: the stream hands the bytes out as they are read
        and never holds the whole object in memory, so a caller that passes them on (an HTTP
        response, a copy to another store) stays small for any object size."""
        ...

    def list(self, prefix: str = "") -> Iterable[str]:
        """Keys beginning with `prefix`, in lexicographic order, excluding reserved
        internal keys (`is_reserved`). `Iterable`, not `Iterator`: an adapter
        may return a materialized, sorted list (the natural local-FS/WebDAV shape)."""
        return [entry.key for entry in self.list_entries(prefix)]

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        """`list(prefix)`, each key with its size and version."""
        ...

    def exists(self, key: str) -> bool:
        """True if `key` exists (reserved keys included)."""
        ...

    def delete(self, key: str) -> None:
        """Delete `key`. Idempotent — deleting a missing key is a no-op."""
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Delete every key below the folder `prefix` ("articles/<ulid>"), reserved keys
        included. Idempotent. `validate_prefix` refuses a shorter or invalid prefix."""
        ...
