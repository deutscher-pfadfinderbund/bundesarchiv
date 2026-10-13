class ArchiveError(Exception):
    pass


class UnreadableReadme(ArchiveError):
    """Raised when a README does not decode: not UTF-8, not YAML, or not an Article or Collection.
    A fact of the file, not of the backend: reading it again gives the same answer."""


class NotFound(ArchiveError):
    pass


class AlreadyExists(ArchiveError):
    """Raised by a create-only write when the key already exists; nothing was written."""


class Conflict(ArchiveError):
    """The stored version is not the expected one: a concurrent write won."""


class Busy(ArchiveError):
    """Raised when the backend refused under contention and the adapter's bounded retries are
    spent. Retryable: the same call may succeed later."""
