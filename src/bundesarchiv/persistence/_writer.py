"""The one save protocol both repositories share (ADR 0013, ADR 0019).

A saved record is a folder, ``articles/<ulid>`` or ``collections/<ulid>``, holding ``README.md``
(the current version, and the commit point) and ``history/<n>.md`` (each version a save replaced,
byte for byte). ``commit`` owns the order: check the version, keep the replaced README, commit.
It also stamps the change record every version carries, so no caller can write one of its own.
``keys_in_save_order`` lists a folder in that order, for the repositories' ``keys_for``.

The port has no compare-and-swap, so the check-then-write runs under ``WRITER_LOCK``. It is one
lock for both repositories because they write one store. The cross-process race is out of scope
by the single-app-process deploy rule (ADR 0013). Media writes and hard deletes run without the
lock. Holding it across store calls assumes a local-latency canonical store.
"""

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from bundesarchiv.domain.models import Change, Version
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore

WRITER_LOCK = threading.Lock()


def readme_key(folder: str) -> str:
    return f"{folder}/README.md"


def history_key(folder: str, version: Version) -> str:
    return f"{folder}/history/{version}.md"


def is_history_key(folder: str, key: str) -> bool:
    """True if `key` is ``history_key(folder, version)`` for some version."""
    stem = PurePosixPath(key).stem
    return stem.isdecimal() and history_key(folder, int(stem)) == key


@dataclass(frozen=True, slots=True)
class StoredKey:
    """One key of a saved record's folder, as `keys_for` lists it, with its size. A save replaces
    only the README; every other key is `write_once` (ADR 0019). `sha256` is the digest of the
    bytes when the README states it, else None. `readable` is False only for a README its
    repository cannot decode, which is never to be pushed (ADR 0020)."""

    key: str
    size: int
    write_once: bool
    sha256: str | None = None
    readable: bool = True


def keys_in_save_order(
    store: ObjectStore, folder: str, digests: Mapping[str, str], *, readable: bool
) -> list[StoredKey]:
    """`folder`'s keys in the order a save writes them: the files a README names, then history,
    then the README. A key in `digests` carries its digest from there; the README carries
    `readable`."""
    readme = readme_key(folder)

    def step(entry: ObjectEntry) -> int:
        return 2 if entry.key == readme else 1 if is_history_key(folder, entry.key) else 0

    return [
        StoredKey(
            entry.key,
            entry.size,
            entry.key != readme,
            digests.get(entry.key),
            readable or entry.key != readme,
        )
        for entry in sorted(store.list_entries(f"{folder}/"), key=step)
    ]


def commit(
    store: ObjectStore,
    folder: str,
    expected_version: Version,
    *,
    changed_by: str,
    version_of: Callable[[str], Version],
    render: Callable[[Version, Change], str],
    precondition: Callable[[], None] = lambda: None,
) -> Version:
    """Replace ``folder``'s README with ``render(new_version, change)`` and return the new version.
    ``change`` names ``changed_by`` and the time of the save.

    Raises ``Conflict`` and writes nothing when the stored version is not ``expected_version``
    (absent README: version 0), and ``ValueError`` before any write when ``changed_by`` is not a
    valid name. ``precondition`` runs after the version check, under the lock, and refuses by
    raising; nothing is written then either. A retry after a crash between the history write and
    the commit finds its history file and goes on; a history file holding other bytes raises
    ``ArchiveError`` and commits nothing."""
    change = Change(datetime.now(UTC).replace(microsecond=0), changed_by)
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
        store.write_atomic(readme_key(folder), render(version + 1, change).encode("utf-8"))
    return version + 1


def _keep(store: ObjectStore, key: str, data: bytes) -> None:
    try:
        store.create(key, data)
    except AlreadyExists:
        if store.read(key) != data:
            raise ArchiveError(f"{key}: holds other bytes than the version it keeps") from None
