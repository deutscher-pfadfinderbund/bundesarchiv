"""A change record's two front-matter fields, shared by both README codecs: ``changed_at`` /
``changed_by`` for the version (ADR 0019), and the same pair under another prefix for the
Papierkorb mark (``deleted_at`` / ``deleted_by``, ADR 0022)."""

from datetime import datetime
from typing import Any

from bundesarchiv.domain.models import Change


def utc_text(at: datetime) -> str:
    """A UTC instant as front-matter text: ISO 8601 with a ``Z``."""
    return at.isoformat().replace("+00:00", "Z")


def to_front_matter(change: Change, prefix: str = "changed") -> dict[str, str]:
    return {f"{prefix}_at": utc_text(change.at), f"{prefix}_by": change.by}


def from_front_matter(front_matter: dict[str, Any], prefix: str = "changed") -> Change | None:
    """The record, or None when neither key is present. Raises TypeError or ValueError for anything
    else that is not a whole, valid record."""
    at, by = front_matter.get(f"{prefix}_at"), front_matter.get(f"{prefix}_by")
    if at is None and by is None:
        return None
    if not isinstance(at, str) or not isinstance(by, str):
        raise TypeError(
            f"change record: expected changed_at and changed_by as text, got {at!r}, {by!r}"
        )
    return Change(datetime.fromisoformat(at), by)
