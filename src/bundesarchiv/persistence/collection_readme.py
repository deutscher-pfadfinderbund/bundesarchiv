"""Collection README codec: Collection ⇄ Markdown-front-matter bytes (ADR 0010/0013).

A canonical README.md is a managed-by marker + a YAML front-matter fence + an
empty body. This module owns that translation for Collections, mirroring the
Article readme codec. Wire keys: `name` (required), `version` (optimistic-
concurrency counter, ADR 0013), `changed_at` + `changed_by` (the change record,
ADR 0019), `parent_id` (optional), `audience` (optional, same convention as
Article — omit when None).

Version + backfill (ADR 0013): `encode_collection` writes the caller's version;
`decode_collection` returns `(Collection, version, change)`. A README written before
versioning existed has NO `version:` key — it backfills to version 0 (the same
"never saved" floor a fresh Article uses), so its first versioned save writes
version 1 and existing unversioned trees migrate cleanly. A present-but-corrupt
version (float/str/negative) is NOT a backfill case: it surfaces as `ArchiveError`
rather than coercing, matching the Article codec's `read_version` discipline.

Only the `ArchiveError` hierarchy crosses out: malformed/unfenced/non-mapping/
invalid front-matter all surface as `ArchiveError`, never a raw yaml/KeyError/
ValueError.
"""

from typing import Any

from bundesarchiv.domain.models import Change, Collection, Ulid, Version
from bundesarchiv.persistence import _change, _front_matter, readme
from bundesarchiv.persistence.errors import ArchiveError


def encode_collection(collection: Collection, version: Version, change: Change) -> str:
    """Render a Collection + version + change record to README.md text (marker + front-matter)."""
    front_matter: dict[str, Any] = {
        "ulid": collection.ulid,
        "name": collection.name,
        "version": version,
        **_change.to_front_matter(change),
    }
    if collection.parent_id is not None:
        front_matter["parent_id"] = collection.parent_id
    if collection.audience is not None:
        front_matter["audience"] = {
            "tier": collection.audience.tier.value,
            "groups": list(collection.audience.groups),
        }
    return _front_matter.dump(front_matter, "")


def decode_collection(text: str, *, ulid: Ulid) -> tuple[Collection, Version, Change | None]:
    """Parse README.md text back to its Collection, stored version (absent -> 0) and change record
    (absent -> None)."""
    front_matter, _ = _front_matter.parse(ulid, text)
    try:
        return (
            _collection_from_front_matter(front_matter, ulid),
            _front_matter.version_of(front_matter, absent=0),
            _change.from_front_matter(front_matter),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveError(f"{ulid}: README front-matter is malformed: {exc}") from exc


def _collection_from_front_matter(fm: dict[str, Any], ulid: Ulid) -> Collection:
    return Collection(
        ulid=str(fm["ulid"]),
        name=str(fm["name"]),
        parent_id=str(fm["parent_id"]) if fm.get("parent_id") is not None else None,
        audience=readme.audience_from_front_matter(fm),
    )
