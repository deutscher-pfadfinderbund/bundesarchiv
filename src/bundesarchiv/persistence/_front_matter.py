"""The README shape both codecs share (ADR 0005, ADR 0010): the managed-by marker, then the YAML
front matter between two fences, then the body.

Only `ArchiveError` crosses out of `parse`; a raw `yaml` error never does.
"""

from typing import Any

import yaml

from bundesarchiv.domain.models import Ulid, Version
from bundesarchiv.persistence.errors import ArchiveError

MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->"
FENCE = "---"


def dump(front_matter: dict[str, Any], body: str) -> str:
    """README text: the marker, `front_matter` in key order between the fences, then `body`."""
    yaml_block = yaml.safe_dump(
        front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip("\n")
    return f"{MARKER}\n{FENCE}\n{yaml_block}\n{FENCE}\n{body}"


def parse(ulid: Ulid, text: str) -> tuple[dict[str, Any], str]:
    """The front matter and the body of README `text`, the body verbatim."""
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("<!--"):
        lines = lines[1:]  # the managed-by marker (any leading HTML comment)
    if not lines or lines[0].strip() != FENCE:
        raise ArchiveError(f"{ulid}: README has no front-matter fence")
    try:
        close = lines.index(FENCE, 1)
    except ValueError:
        raise ArchiveError(f"{ulid}: README front-matter is unterminated") from None
    # The single separator newline `dump` added was already consumed by split;
    # lines[close + 1:] reconstructs the body verbatim (a body may open with blank lines).
    body = "\n".join(lines[close + 1 :])
    try:
        front_matter = yaml.load("\n".join(lines[1:close]), Loader=yaml.CSafeLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        # RecursionError is NOT a yaml.YAMLError subclass: deeply-nested flow collections
        # (a corrupt/hostile README) blow the stack inside the loader — contain it too.
        raise ArchiveError(f"{ulid}: README front-matter is not valid YAML: {exc}") from exc
    if not isinstance(front_matter, dict):
        raise ArchiveError(f"{ulid}: README front-matter is not a mapping")
    return front_matter, body


def version_of(fm: dict[str, Any], *, absent: Version | None = None) -> Version:
    """The stored optimistic-concurrency version: an exact non-negative int, or `absent` when the
    key is missing (None: the key is required). Raises `ValueError` otherwise; bool/float/str are
    rejected rather than coerced (int(1.5) -> 1 would silently accept a corrupt version)."""
    value = fm.get("version", absent)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"version must be a non-negative integer, got {value!r}")
    return value
