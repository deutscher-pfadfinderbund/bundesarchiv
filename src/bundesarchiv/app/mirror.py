"""The push to the system of record (ADR 0020 stage A): the working copy's files onto the
Nextcloud folder, add-only.

``push`` copies one saved Article or Collection after a save. It speaks only the storage port and
an injected ``PushRecord``, and takes the keys, and which of them are write-once, from the
repositories' ``keys_for``. It sends a record's keys in the order ``keys_for`` lists them, the
local save order with the README last, so the system of record never holds a README naming a file
it lacks. A write-once key is sent once, with ``create``; a README whenever its SHA-256 differs from
the one the record holds. Bytes move streamed, except a README: it is read whole, so the digest
recorded is that of the bytes sent. Nothing here deletes on the system of record.

``reconcile(canonical, mirror)`` — the periodic full sweep: list canonical, push every
missing/changed key, delete every mirror-only key, and return a ``ReconcileSummary`` (the counts
logged + returned as the task result). A per-key failure is counted, never fatal — one flaky
blob must not abandon the rest of the sweep (the next reconcile heals it).
"""

import hashlib
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Ulid
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore
from bundesarchiv.persistence.repository import StoredKey

logger = logging.getLogger(__name__)

#: How much of a file one read of a hash pass takes.
_CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Pushed:
    """What the app last pushed to one key of the system of record: the SHA-256 of the local
    bytes and the version token the write returned."""

    sha256: str
    version: str


class PushRecord(Protocol):
    """What the app pushed to the system of record, per key (ADR 0020). Derived state: losing it
    moves no data, the next reconcile rebuilds it."""

    def held(self, keys: Iterable[str]) -> Mapping[str, Pushed]:
        """The entries of those of `keys` the record holds."""
        ...

    def entries(self) -> Mapping[str, Pushed]:
        """Every entry."""
        ...

    def note(self, key: str, pushed: Pushed) -> None:
        """Record that `pushed` now stands at `key`, in place of what the record held for it."""
        ...


class _Keys(Protocol):
    """A repository, as far as the push needs one."""

    def keys_for(self, ulid: Ulid) -> list[StoredKey]: ...


def push(archive: Archive, remote: ObjectStore, record: PushRecord, ulid: Ulid) -> None:
    """Push the saved Article or Collection `ulid` to `remote`: each key `record` does not hold with
    the SHA-256 of its local bytes. A write-once key `remote` holds already is recorded, not sent.
    Raises `ArchiveError` at the first call that fails, and sends nothing after it."""
    run = _Push(archive.store, remote, record)
    for repository in (archive.collections, archive.articles):
        run.folder(repository, ulid)


class _Push:
    """Pushes saved records from `canonical` to `remote`, noting each key in `record`."""

    def __init__(self, canonical: ObjectStore, remote: ObjectStore, record: PushRecord) -> None:
        self._canonical = canonical
        self._remote = remote
        self._record = record

    def folder(self, repository: _Keys, ulid: Ulid) -> None:
        # Read before the listing the files are sent from: a save stores every file a README
        # names before that README, so this listing holds them all.
        current = {
            key.key: self._canonical.read(key.key)
            for key in repository.keys_for(ulid)
            if not key.write_once
        }
        keys = repository.keys_for(ulid)
        held = self._record.held([key.key for key in keys])
        for key in keys:
            if key.write_once:
                self._write_once(key, held.get(key.key))
            elif key.key in current:
                self._replaceable(key.key, current[key.key], held.get(key.key))

    def _write_once(self, key: StoredKey, held: Pushed | None) -> None:
        if held is not None:
            return
        sha256 = key.sha256 or _digest(self._canonical, key.key)
        if (there := self._there(key.key)) is not None:
            version = there.version
        else:
            with self._canonical.open_stream(key.key) as stream:
                version = self._remote.create_large(key.key, stream, key.size)
        self._record.note(key.key, Pushed(sha256, version))

    def _replaceable(self, key: str, data: bytes, held: Pushed | None) -> None:
        sha256 = hashlib.sha256(data).hexdigest()
        if held is not None and held.sha256 == sha256:
            return
        there = None if held is not None else self._there(key)
        if there is not None and _digest(self._remote, key) == sha256:
            version = there.version
        else:
            version = self._remote.write_atomic(key, data)
        self._record.note(key, Pushed(sha256, version))

    def _there(self, key: str) -> ObjectEntry | None:
        """`key`'s entry on the system of record, or None if it lacks the key."""
        return next((entry for entry in self._remote.list_entries(key) if entry.key == key), None)


def _digest(store: ObjectStore, key: str) -> str:
    """The SHA-256 of the bytes at `key`, read streamed."""
    digest = hashlib.sha256()
    with store.open_stream(key) as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


#: Mass-delete warning threshold: warn when one sweep deletes more than ``max(25, 10% of canonical
#: keys)``. The absolute floor of 25 keeps routine deletes silent (one hard-deleted Article is a
#: handful of keys) even on a small archive; the 10%-of-canonical term scales the bound up so a
#: legitimate bulk delete on a large archive does not cry wolf. A misconfigured
#: ``BUNDESARCHIV_MIRROR_DAV_URL`` (pointed at a folder holding human-managed files) shows up as a
#: mass of mirror-only keys — far above both bounds — and gets NAMED, not silently counted.
_MASS_DELETE_FLOOR = 25
_MASS_DELETE_SAMPLE = 20  # how many deleted keys the warning lists


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    """The outcome of one ``reconcile`` sweep — logged and returned as the task result. ``pushed``
    counts keys copied to the mirror (missing OR changed); ``deleted`` counts stale mirror-only keys
    removed; ``failed`` counts keys whose push/delete raised ``ArchiveError`` (a down/slow mirror is
    the expected failure mode — the reconcile logs it and moves on; the next sweep heals it)."""

    pushed: int
    deleted: int
    failed: int


def reconcile(canonical: ObjectStore, mirror: ObjectStore) -> ReconcileSummary:
    """Full sweep: make the mirror match canonical, returning per-outcome counts. Push every key
    that is missing from the mirror or whose mirror bytes differ; delete every key the mirror holds
    that canonical no longer has. A per-key ``ArchiveError`` (a flaky/slow mirror is expected, ADR
    0005) is counted in ``failed`` and skipped so one bad blob never abandons the sweep — the next
    reconcile heals it. Every key is compared byte for byte."""
    canonical_keys = set(canonical.list())
    mirror_keys = set(mirror.list())
    pushed = failed = 0
    deleted_keys: list[str] = []

    for key in sorted(canonical_keys):
        try:
            data = canonical.read(key)
            if not (mirror.exists(key) and mirror.read(key) == data):
                mirror.write_atomic(key, data)
                pushed += 1
        except ArchiveError:
            failed += 1  # flaky mirror/canonical read: count it, keep sweeping (next run heals)

    for key in sorted(mirror_keys - canonical_keys):
        try:
            mirror.delete(key)
            deleted_keys.append(key)
        except ArchiveError:
            failed += 1

    _warn_on_mass_delete(deleted_keys, len(canonical_keys))
    return ReconcileSummary(pushed=pushed, deleted=len(deleted_keys), failed=failed)


def _warn_on_mass_delete(deleted_keys: list[str], canonical_count: int) -> None:
    """Log a WARNING naming (a sample of) the deleted keys when one sweep deletes an anomalous
    number — the signature of a mirror root shared with human-managed files (see the threshold
    rationale at ``_MASS_DELETE_FLOOR``). An actionable signal, not a silent count."""
    threshold = max(_MASS_DELETE_FLOOR, canonical_count // 10)
    if len(deleted_keys) <= threshold:
        return
    sample = ", ".join(deleted_keys[:_MASS_DELETE_SAMPLE])
    logger.warning(
        "mirror reconcile deleted %d mirror-only keys (threshold %d) — if these are not "
        "hard-deleted archive objects, BUNDESARCHIV_MIRROR_DAV_URL points at a folder the app "
        "does not own exclusively. First %d: %s",
        len(deleted_keys),
        threshold,
        min(len(deleted_keys), _MASS_DELETE_SAMPLE),
        sample,
    )
