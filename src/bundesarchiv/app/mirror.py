"""The push to the system of record (ADR 0020 stage A): add-only but for a hard delete.

Keys go in ``keys_for`` order, README last, so the system of record never holds a README naming a
file it lacks. A README is read whole, so the digest recorded is that of the bytes sent. Speaks
only the storage port and an injected ``PushRecord``.
"""

import hashlib
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Ulid
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore
from bundesarchiv.persistence.repository import StoredKey, content_digest

logger = logging.getLogger(__name__)

#: How many keys of one finding a reconcile warning names.
_SAMPLE = 20

#: The `task` field of the reconcile's log lines, as the job summary in `tasks.py` has it.
_TASK = "mirror_reconcile"

#: Seconds between the progress lines of a reconcile.
_PROGRESS_INTERVAL = 60


@dataclass(frozen=True, slots=True)
class Sent:
    """What one `push` sent: how many keys, and their bytes."""

    keys: int
    bytes: int


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

    def entries(self) -> Mapping[str, Pushed]: ...

    def note(self, key: str, pushed: Pushed) -> None:
        """Record that `pushed` now stands at `key`, in place of what the record held for it."""
        ...

    def forget_prefix(self, prefix: str) -> None:
        """Drop the entry of every key below the folder `prefix`, the keys
        `ObjectStore.delete_prefix(prefix)` deletes."""
        ...


class _Keys(Protocol):
    """A repository, as far as the push needs one."""

    def list_ulids(self) -> Iterable[Ulid]: ...

    def keys_for(self, ulid: Ulid) -> list[StoredKey]: ...


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    """What one reconcile did and found. `sent`: keys pushed to the system of record. `recorded`:
    keys found there already and entered into the push record, its rebuild. `changed`: keys whose
    version there is not the one the record holds, changed on the system of record (by hand, for
    example). `mismatched`: write-once keys there in another size than the local file, neither
    recorded nor replaced. `unreadable`: local READMEs that do not decode, not pushed.
    `remote_only`: keys only the system of record holds, left there: a hard delete that never
    reached it, or a file not the app's. `failed`: the saved records whose push broke off; the next
    reconcile takes them up again. `sent_bytes`: the bytes of `sent`. `remote_keys`: how many keys the
    system of record listed before the push."""

    sent: tuple[str, ...]
    sent_bytes: int
    recorded: tuple[str, ...]
    changed: tuple[str, ...]
    mismatched: tuple[str, ...]
    unreadable: tuple[str, ...]
    remote_only: tuple[str, ...]
    failed: tuple[Ulid, ...]
    remote_keys: int


def push(archive: Archive, remote: ObjectStore, record: PushRecord, ulid: Ulid) -> Sent:
    """Push the saved Article or Collection `ulid` to `remote`: each key `record` does not hold with
    the SHA-256 of its local bytes. A write-once key `remote` holds already is recorded, not sent.
    Raises `ArchiveError` at the first call that fails, and sends nothing after it."""
    run = _Push(archive.store, remote, record, sweep=None)
    for repository in (archive.collections, archive.articles):
        run.folder(repository, ulid)
    return Sent(len(run.sent), run.sent_bytes)


def delete_article(archive: Archive, remote: ObjectStore, record: PushRecord, ulid: Ulid) -> None:
    """Take the hard-deleted Article `ulid` off `remote`, its whole folder, then forget that folder
    in `record` (ADR 0020 "Hard delete"). Idempotent. Raises `ArchiveError` when the delete fails,
    forgetting nothing."""
    folder = archive.articles.folder(ulid)
    remote.delete_prefix(folder)
    record.forget_prefix(folder)


def reconcile(
    archive: Archive,
    remote: ObjectStore,
    record: PushRecord,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> ReconcileReport:
    """Push every saved Article and Collection to `remote` as `push` does, checking against one
    listing of `remote` instead of trusting `record`: a key missing there is sent even when the
    record holds it, and a key there that the record lacks is recorded, a README after one download.
    A record whose push fails is reported and the sweep goes on. Logs a warning for each kind of
    finding (`changed`, `remote_only`, `failed`), a start line once `remote` is listed and, on
    `clock`, a progress line when `_PROGRESS_INTERVAL` seconds have passed since the last."""
    records = [
        (repository, ulid)
        for repository in (archive.collections, archive.articles)
        for ulid in repository.list_ulids()
    ]
    started = clock()
    sweep = _Sweep({entry.key: entry for entry in remote.list_entries()}, record.entries())
    last = clock()
    logger.info(
        "reconcile: %d records to check, %d keys on the system of record",
        len(records),
        len(sweep.listed),
        extra={
            "task": _TASK,
            "stage": "start",
            "records": len(records),
            "remote_keys": len(sweep.listed),
            "listing_seconds": round(last - started, 3),
        },
    )
    run = _Push(archive.store, remote, record, sweep)
    failed: list[Ulid] = []
    for checked, (repository, ulid) in enumerate(records, start=1):
        try:
            run.folder(repository, ulid)
        except ArchiveError as exc:
            failed.append(ulid)
            logger.warning(
                "reconcile: the push of %s broke off: %s", ulid, exc, extra={"ulid": ulid}
            )
        if (now := clock()) - last >= _PROGRESS_INTERVAL:
            last = now
            logger.info(
                "reconcile: %d of %d records checked, %d keys sent",
                checked,
                len(records),
                len(run.sent),
                extra={
                    "task": _TASK,
                    "stage": "progress",
                    "checked": checked,
                    "records": len(records),
                    "sent": len(run.sent),
                    "sent_bytes": run.sent_bytes,
                    "failed": len(failed),
                    "seconds": round(now - started, 3),
                },
            )
    report = ReconcileReport(
        sent=tuple(run.sent),
        sent_bytes=run.sent_bytes,
        recorded=tuple(run.recorded),
        changed=tuple(sorted(sweep.changed())),
        mismatched=tuple(run.mismatched),
        unreadable=tuple(run.unreadable),
        remote_only=tuple(sorted(sweep.listed.keys() - run.seen)),
        failed=tuple(failed),
        remote_keys=len(sweep.listed),
    )
    _warn("changed", "changed on the system of record since the app pushed them", report.changed)
    _warn("remote_only", "only on the system of record, left there", report.remote_only)
    return report


@dataclass(frozen=True, slots=True)
class _Sweep:
    """What a reconcile knows before it pushes: the system of record's listing and the record."""

    listed: Mapping[str, ObjectEntry]
    entries: Mapping[str, Pushed]

    def changed(self) -> Iterable[str]:
        return (
            key
            for key, entry in self.listed.items()
            if key in self.entries and self.entries[key].version != entry.version
        )


class _Push:
    """Pushes saved records from `canonical` to `remote`, noting each key in `record`: trusting
    `record`, or, in a reconcile, checking it against the `sweep`."""

    def __init__(
        self, canonical: ObjectStore, remote: ObjectStore, record: PushRecord, sweep: _Sweep | None
    ) -> None:
        self._canonical = canonical
        self._remote = remote
        self._record = record
        self._sweep = sweep
        self.sent: list[str] = []
        self.sent_bytes = 0
        self.recorded: list[str] = []
        self.mismatched: list[str] = []
        self.unreadable: list[str] = []
        self.seen: set[str] = set()

    def folder(self, repository: _Keys, ulid: Ulid) -> None:
        # Read before the listing the files are sent from: a save stores every file a README
        # names before that README, so this listing holds them all.
        first = repository.keys_for(ulid)
        current = {
            key.key: self._canonical.read(key.key)
            for key in first
            if not key.write_once and key.readable
        }
        for key in first:
            if not key.readable:
                self._flag(key.key, self.unreadable, "does not decode: not pushed")
        keys = repository.keys_for(ulid)
        names = {*current, *(key.key for key in keys)}
        self.seen |= names
        held = self._record.held(names) if self._sweep is None else self._sweep.entries
        # A record with none of the folder's keys may be a lost one: look before sending, since
        # learning from a refused `create` that a file is there costs its whole body.
        look_first = self._sweep is not None or not held
        for key in keys:
            if key.write_once:
                self._write_once(key, held.get(key.key), look_first=look_first)
            elif key.key in current:
                self._replaceable(key.key, current[key.key], held.get(key.key))

    def _write_once(self, key: StoredKey, held: Pushed | None, *, look_first: bool) -> None:
        if held is not None and self._confirmed(key.key):
            return
        if look_first and (there := self._there(key.key)) is not None:
            self._found(key, there)
            return
        try:
            with self._canonical.open_stream(key.key) as stream:
                version = self._remote.create_large(key.key, stream, key.size)
        except AlreadyExists:
            if (there := self._listed(key.key)) is None:
                raise
            self._found(key, there)
            return
        sha256 = key.sha256 or _digest(self._canonical, key.key)
        self._note(key.key, Pushed(sha256, version), self.sent)
        self.sent_bytes += key.size

    def _found(self, key: StoredKey, there: ObjectEntry) -> None:
        """Record the write-once `key` the system of record holds as `there`, unless its size
        says it is another file."""
        if there.size != key.size:
            self._flag(key.key, self.mismatched, "is there in another size: left as it is")
            return
        sha256 = key.sha256 or _digest(self._canonical, key.key)
        self._note(key.key, Pushed(sha256, there.version), self.recorded)

    def _replaceable(self, key: str, data: bytes, held: Pushed | None) -> None:
        sha256 = hashlib.sha256(data).hexdigest()
        if held is not None and held.sha256 == sha256 and self._confirmed(key):
            return
        there = self._there(key) if held is None else None
        if there is not None and _digest(self._remote, key) == sha256:
            self._note(key, Pushed(sha256, there.version), self.recorded)
        else:
            self._note(key, Pushed(sha256, self._remote.write_atomic(key, data)), self.sent)
            self.sent_bytes += len(data)

    def _confirmed(self, key: str) -> bool:
        """Whether the record's word that the system of record holds `key` stands: always in a
        push, in a reconcile when the listing shows the key."""
        return self._sweep is None or key in self._sweep.listed

    def _there(self, key: str) -> ObjectEntry | None:
        if self._sweep is not None:
            return self._sweep.listed.get(key)
        return self._listed(key)

    def _listed(self, key: str) -> ObjectEntry | None:
        """`key`'s entry in a listing of the system of record, or None."""
        return next((entry for entry in self._remote.list_entries(key) if entry.key == key), None)

    def _note(self, key: str, pushed: Pushed, into: list[str]) -> None:
        self._record.note(key, pushed)
        into.append(key)

    @staticmethod
    def _flag(key: str, into: list[str], finding: str) -> None:
        logger.warning("push: %s %s", key, finding, extra={"key": key, "finding": finding})
        into.append(key)


def _digest(store: ObjectStore, key: str) -> str:
    """The SHA-256 of the bytes at `key`, read streamed."""
    with store.open_stream(key) as stream:
        return content_digest(stream)[0]


def _warn(kind: str, finding: str, keys: tuple[str, ...]) -> None:
    if keys:
        sample = keys[:_SAMPLE]
        logger.warning(
            "reconcile: %d keys %s, first %d: %s",
            len(keys),
            finding,
            len(sample),
            ", ".join(sample),
            extra={"finding": kind, "count": len(keys), "keys": list(sample)},
        )
