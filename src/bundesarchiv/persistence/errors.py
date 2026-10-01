"""Typed exception hierarchy for the persistence layer."""


class ArchiveError(Exception):
    """Base class for all archive persistence errors."""


class UnreadableReadme(ArchiveError):
    """Raised when a README does not decode: not UTF-8, not YAML, or not an Article or Collection.
    A fact of the file, not of the backend: reading it again gives the same answer."""


class NotFound(ArchiveError):
    """Raised when a key does not exist in the store."""


class AlreadyExists(ArchiveError):
    """Raised by a create-only write when the key already exists; nothing was written."""


class Conflict(ArchiveError):
    """Raised on an optimistic-concurrency conflict — the stored version no longer
    matches the expected version (a concurrent write won)."""


class Busy(ArchiveError):
    """Raised when the backend refused under contention and the adapter's bounded retries are
    spent. Retryable: the same call may succeed later."""
