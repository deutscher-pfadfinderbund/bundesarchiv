"""WebDAV mirror replay + reconcile logic (Part 4.9) — the CONVENIENCE browse copy.

The mirror is a browse-only copy of the canonical store on a Nextcloud/WebDAV endpoint. It is
NEVER a read path, NEVER counted as durability (restic is the backup, ADR 0005 + roadmap) — it
only exists so a human can browse the archive tree in a familiar file UI. Tiering (Part 7) is the
one thing that changes this rule; nothing here anticipates it (YAGNI — the ObjectStore port is the
openness).

A mirror IS just another ``ObjectStore``, so these functions take two stores (canonical + mirror)
and speak only the port. Everything is REFERENCE-based (ADR 0014): a replay job carries only a key
and re-reads canonical truth at execution, so a key GONE from canonical by execution time is
DELETED from the mirror — current canonical truth always wins over a stale job. The mirror mirrors;
it never accumulates.

- ``push_key(canonical, mirror, key)`` — replay ONE key: copy the current canonical bytes onto the
  mirror, or delete the mirror copy when the key is gone from canonical. Idempotent.
- ``reconcile(canonical, mirror)`` — the periodic full sweep: list canonical, push every
  missing/changed key, delete every mirror-only key, and return a ``ReconcileSummary`` (the counts
  logged + returned as the task result). A per-key failure is counted, never fatal — one flaky
  blob must not abandon the rest of the sweep (the next reconcile heals it).
"""

import logging
from dataclasses import dataclass

from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore

logger = logging.getLogger(__name__)

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


def push_key(canonical: ObjectStore, mirror: ObjectStore, key: str) -> None:
    """Replay ONE ``key`` onto the mirror from CURRENT canonical truth (reference semantics, ADR
    0014). If the key is present in canonical, create-or-replace it on the mirror; if it is gone
    from canonical (a stale job whose object was deleted by execution time), delete it from the
    mirror instead. Idempotent — re-running writes the same bytes or repeats the same no-op delete.
    """
    try:
        data = canonical.read(key)
    except NotFound:
        mirror.delete(key)  # gone from canonical -> the mirror must not keep it (idempotent no-op)
        return
    mirror.write_atomic(key, data)


def reconcile(canonical: ObjectStore, mirror: ObjectStore) -> ReconcileSummary:
    """Full sweep: make the mirror match canonical, returning per-outcome counts. Push every key
    that is missing from the mirror or whose mirror bytes differ; delete every key the mirror holds
    that canonical no longer has. A per-key ``ArchiveError`` (a flaky/slow mirror is expected, ADR
    0005) is counted in ``failed`` and skipped so one bad blob never abandons the sweep — the next
    reconcile heals it. Byte comparison is used because the ObjectStore port exposes no cheaper
    metadata (no size/etag); at this archive's scale (~10³ objects) a full compare is fine."""
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
