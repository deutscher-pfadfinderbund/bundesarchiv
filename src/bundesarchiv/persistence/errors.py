"""Typed exception hierarchy for the persistence layer."""


class ArchiveError(Exception):
    """Base class for all archive persistence errors."""


class NotFound(ArchiveError):
    """Raised when a key does not exist in the store."""


class Conflict(ArchiveError):
    """Raised on an optimistic-concurrency conflict — the stored version no longer
    matches the expected version (a concurrent write won)."""
