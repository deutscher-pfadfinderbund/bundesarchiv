"""Collection README codec (ADR 0010, ADR 0013). Only `UnreadableReadme` crosses out."""

from typing import Any

from bundesarchiv.domain.models import ULID, Change, Collection, Version
from bundesarchiv.persistence import _change, _front_matter, readme
from bundesarchiv.persistence.errors import UnreadableReadme


def encode_collection(collection: Collection, version: Version, change: Change) -> str:
    front_matter: dict[str, Any] = {
        **({"parent_id": collection.parent_id} if collection.parent_id is not None else {}),
        **_front_matter.audience_to_front_matter(collection.audience),
        "ulid": collection.ulid,
        "version": version,
        **_change.to_front_matter(change),
    }
    return _front_matter.dump(front_matter, collection.name, "")


def decode_collection(text: str, *, ulid: ULID) -> tuple[Collection, Version, Change | None]:
    """Parse README.md text back to its Collection, stored version (absent -> 0) and change record
    (absent -> None)."""
    front_matter, name, _ = _front_matter.split_title(ulid, text, "name")
    try:
        return (
            _collection_from_front_matter(front_matter, name, ulid),
            _front_matter.version_of(front_matter, absent=0),
            _change.from_front_matter(front_matter),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise UnreadableReadme(f"{ulid}: README front-matter is malformed: {exc}") from exc


def _collection_from_front_matter(fm: dict[str, Any], name: str | None, ulid: ULID) -> Collection:
    return Collection(
        ulid=ULID(str(fm["ulid"])),
        name=str(fm["name"]) if name is None else name,
        parent_id=ULID(str(fm["parent_id"])) if fm.get("parent_id") is not None else None,
        audience=readme.audience_from_front_matter(fm),
    )
