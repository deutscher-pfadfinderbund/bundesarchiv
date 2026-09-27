"""The change record's two front-matter fields, shared by both README codecs (ADR 0019)."""

from datetime import datetime
from typing import Any

from bundesarchiv.domain.models import Change


def utc_text(at: datetime) -> str:
    """A UTC instant as front-matter text: ISO 8601 with a ``Z``."""
    return at.isoformat().replace("+00:00", "Z")


def to_front_matter(change: Change) -> dict[str, str]:
    return {"changed_at": utc_text(change.at), "changed_by": change.by}


def from_front_matter(front_matter: dict[str, Any]) -> Change | None:
    """The record, or None for a README written before it existed (neither key present). Raises
    TypeError or ValueError for anything else that is not a whole, valid record."""
    at, by = front_matter.get("changed_at"), front_matter.get("changed_by")
    if at is None and by is None:
        return None
    if not isinstance(at, str) or not isinstance(by, str):
        raise TypeError(
            f"change record: expected changed_at and changed_by as text, got {at!r}, {by!r}"
        )
    return Change(datetime.fromisoformat(at), by)
