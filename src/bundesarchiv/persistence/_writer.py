"""The one save protocol both repositories share (ADR 0013, ADR 0019).

A saved record is a folder, ``articles/<ulid>`` or ``collections/<ulid>``, holding ``README.md``
(the current version, and the commit point) and ``history/<n>.md`` (each version a save replaced,
byte for byte). ``commit`` owns the order: check the version, keep the replaced README, commit.

The port has no compare-and-swap, so the check-then-write runs under ``WRITER_LOCK``. It is one
lock for both repositories because they write one store. The cross-process race is out of scope
by the single-app-process deploy rule (ADR 0013). Media writes and hard deletes run without the
lock. Holding it across store calls assumes a local-latency canonical store.
"""

import threading
from collections.abc import Callable

from bundesarchiv.domain.models import Version
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore

WRITER_LOCK = threading.Lock()


def readme_key(folder: str) -> str:
    return f"{folder}/README.md"


def history_key(folder: str, version: Version) -> str:
    return f"{folder}/history/{version}.md"


def commit(
    store: ObjectStore,
    folder: str,
    expected_version: Version,
    *,
    version_of: Callable[[str], Version],
    render: Callable[[Version], str],
    precondition: Callable[[], None] = lambda: None,
) -> Version:
    """Replace ``folder``'s README with ``render(new_version)`` and return the new version.

    Raises ``Conflict`` and writes nothing when the stored version is not ``expected_version``
    (absent README: version 0). ``precondition`` runs after the version check, under the lock, and
    refuses by raising; nothing is written then either. A retry after a crash between the history
    write and the commit finds its history file and goes on; a history file holding other bytes
    raises ``ArchiveError`` and commits nothing."""
    with WRITER_LOCK:
        try:
            current = store.read(readme_key(folder))
        except NotFound:
            current = None
        version = 0 if current is None else version_of(current.decode("utf-8"))
        if version != expected_version:
            raise Conflict(f"{folder}: expected version {expected_version}, store has {version}")
        precondition()
        if current is not None:
            _keep(store, history_key(folder, version), current)
        store.write_atomic(readme_key(folder), render(version + 1).encode("utf-8"))
    return version + 1


def _keep(store: ObjectStore, key: str, data: bytes) -> None:
    try:
        store.create(key, data)
    except AlreadyExists:
        if store.read(key) != data:
            raise ArchiveError(f"{key}: holds other bytes than the version it keeps") from None
