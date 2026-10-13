"""Collection README codec: Collection ⇄ README text (ADR 0010, ADR 0013). An absent `version`
reads as 0; a corrupt one is `UnreadableReadme`, the only error that crosses out.
"""

from typing import Any

from bundesarchiv.domain.models import Change, Collection, Ulid, Version
from bundesarchiv.persistence import _change, _front_matter, readme
from bundesarchiv.persistence.errors import UnreadableReadme


def encode_collection(collection: Collection, version: Version, change: Change) -> str:
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
        raise UnreadableReadme(f"{ulid}: README front-matter is malformed: {exc}") from exc


def _collection_from_front_matter(fm: dict[str, Any], ulid: Ulid) -> Collection:
    return Collection(
        ulid=str(fm["ulid"]),
        name=str(fm["name"]),
        parent_id=str(fm["parent_id"]) if fm.get("parent_id") is not None else None,
        audience=readme.audience_from_front_matter(fm),
    )
