"""Collection README codec: Collection ⇄ Markdown-front-matter bytes (ADR 0010).

A canonical README.md is a managed-by marker + a YAML front-matter fence + an
empty body. This module owns that translation for Collections, mirroring the
Article readme codec. Wire keys: `name` (required), `parent_id` (optional),
`audience` (optional, same convention as Article — omit when None).

Only the `ArchiveError` hierarchy crosses out: malformed/unfenced/non-mapping/
invalid front-matter all surface as `ArchiveError`, never a raw yaml/KeyError/
ValueError.
"""

from typing import Any

import yaml

from bundesarchiv.domain.models import Audience, AudienceTier, Collection, Ulid
from bundesarchiv.persistence.errors import ArchiveError

_MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->"
_FENCE = "---"


def encode_collection(collection: Collection) -> str:
    """Render a Collection to README.md text (marker + front-matter)."""
    front_matter: dict[str, Any] = {"ulid": collection.ulid, "name": collection.name}
    if collection.parent_id is not None:
        front_matter["parent_id"] = collection.parent_id
    if collection.audience is not None:
        front_matter["audience"] = {
            "tier": collection.audience.tier.value,
            "groups": list(collection.audience.groups),
        }
    yaml_block = yaml.safe_dump(
        front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip("\n")
    return f"{_MARKER}\n{_FENCE}\n{yaml_block}\n{_FENCE}\n"


def decode_collection(text: str, *, ulid: Ulid) -> Collection:
    """Parse README.md text back to its Collection."""
    front_matter = _parse_front_matter(ulid, text)
    try:
        return _collection_from_front_matter(front_matter, ulid)
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveError(f"{ulid}: README front-matter is malformed: {exc}") from exc


def _parse_front_matter(ulid: Ulid, text: str) -> dict[str, Any]:
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("<!--"):
        lines = lines[1:]  # the managed-by marker (any leading HTML comment)
    if not lines or lines[0].strip() != _FENCE:
        raise ArchiveError(f"{ulid}: README has no front-matter fence")
    try:
        close = lines.index(_FENCE, 1)
    except ValueError:
        raise ArchiveError(f"{ulid}: README front-matter is unterminated") from None
    try:
        front_matter = yaml.safe_load("\n".join(lines[1:close]))
    except (yaml.YAMLError, RecursionError) as exc:
        raise ArchiveError(f"{ulid}: README front-matter is not valid YAML: {exc}") from exc
    if not isinstance(front_matter, dict):
        raise ArchiveError(f"{ulid}: README front-matter is not a mapping")
    return front_matter


def _audience_from_front_matter(fm: dict[str, Any]) -> Audience | None:
    """Decode the optional audience. Absent or null = inherit (None, ADR 0001);
    a present mapping is an explicit rung; anything else present is corrupt."""
    raw = fm.get("audience")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"audience: expected a mapping, got {type(raw).__name__}")
    if not raw:
        return None  # a content-less `audience: {}` names no rung -> inherit
    return Audience(
        tier=AudienceTier(raw.get("tier", AudienceTier.MEMBERS.value)),
        groups=tuple(str(g) for g in (raw.get("groups") or [])),
    )


def _collection_from_front_matter(fm: dict[str, Any], ulid: Ulid) -> Collection:
    return Collection(
        ulid=str(fm["ulid"]),
        name=str(fm["name"]),
        parent_id=str(fm["parent_id"]) if fm.get("parent_id") is not None else None,
        audience=_audience_from_front_matter(fm),
    )
