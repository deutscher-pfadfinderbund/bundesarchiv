"""README codec: Article ⇄ Markdown-front-matter bytes (the ADR 0005/0006 README.md).

A canonical README.md is a managed-by marker + a YAML front-matter fence + the Markdown
body. This module owns that translation alone — separate from ArticleRepository's
versioning/ordering/storage protocol — so it has its own test surface and offers a cheap
`read_version` (no whole-Article rebuild) for optimistic-lock checks and reindex walks.

Only the `ArchiveError` hierarchy crosses out: malformed/unfenced/non-mapping/invalid
front-matter all surface as `ArchiveError`, never a raw `yaml`/`KeyError`/`ValueError`.
"""

from typing import Any

import yaml

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.persistence.errors import ArchiveError

_MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->"
_FENCE = "---"


def encode(article: Article, version: Version) -> str:
    """Render an Article + version to README.md text (marker + front-matter + body)."""
    front_matter = {
        "ulid": article.ulid,
        "version": version,
        "title": article.title,
        "collection_id": article.collection_id,
        "lifecycle": article.lifecycle.value,
        # None = inherit (ADR 0001): omit the key entirely so absence reads as inherit.
        **(
            {
                "audience": {
                    "tier": article.audience.tier.value,
                    "groups": list(article.audience.groups),
                }
            }
            if article.audience is not None
            else {}
        ),
        "ref_code": article.ref_code,
        "media_type": article.media_type,
        "document_type": article.document_type,
        "tags": list(article.tags),
        "physical_location": article.physical_location,
        # Optional provenance fields: omit key entirely when None (same convention as audience).
        **({"date": article.date.value} if article.date is not None else {}),
        **({"creator": article.creator} if article.creator is not None else {}),
        **({"subject_place": article.subject_place} if article.subject_place is not None else {}),
        "media": [
            {
                "filename": m.filename,
                "content_hash": m.content_hash,
                "media_type": m.media_type,
                "byte_size": m.byte_size,
            }
            for m in article.media
        ],
        # Custom metadata as a sub-mapping; omitted when empty (like audience) to avoid noise.
        **({"custom": dict(article.custom)} if article.custom else {}),
    }
    yaml_block = yaml.safe_dump(
        front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip("\n")
    return f"{_MARKER}\n{_FENCE}\n{yaml_block}\n{_FENCE}\n{article.body}"


def decode(ulid: Ulid, text: str) -> tuple[Article, Version]:
    """Parse README.md text back to its Article + stored version."""
    front_matter, body = _parse_front_matter(ulid, text)
    try:
        return _article_from_front_matter(front_matter, body), _version_of(front_matter)
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveError(f"{ulid}: README front-matter is malformed: {exc}") from exc


def read_version(ulid: Ulid, text: str) -> Version:
    """Read only the stored version — no Article rebuild (optimistic-lock / reindex)."""
    front_matter, _ = _parse_front_matter(ulid, text)
    try:
        return _version_of(front_matter)
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveError(f"{ulid}: README version is malformed: {exc}") from exc


def _parse_front_matter(ulid: Ulid, text: str) -> tuple[dict[str, Any], str]:
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("<!--"):
        lines = lines[1:]  # the managed-by marker (any leading HTML comment)
    if not lines or lines[0].strip() != _FENCE:
        raise ArchiveError(f"{ulid}: README has no front-matter fence")
    try:
        close = lines.index(_FENCE, 1)
    except ValueError:
        raise ArchiveError(f"{ulid}: README front-matter is unterminated") from None
    # The single separator newline the renderer added was already consumed by split;
    # lines[close + 1:] reconstructs the body verbatim (a body may open with blank lines).
    body = "\n".join(lines[close + 1 :])
    try:
        front_matter = yaml.safe_load("\n".join(lines[1:close]))
    except (yaml.YAMLError, RecursionError) as exc:
        # RecursionError is NOT a yaml.YAMLError subclass: deeply-nested flow collections
        # (a sub-1KB corrupt/hostile README) blow the stack inside safe_load — contain it too.
        raise ArchiveError(f"{ulid}: README front-matter is not valid YAML: {exc}") from exc
    if not isinstance(front_matter, dict):
        raise ArchiveError(f"{ulid}: README front-matter is not a mapping")
    return front_matter, body


def _as_str_tuple(value: object) -> tuple[str, ...]:
    """Coerce a front-matter list to a tuple of strings, rejecting a scalar — a bare
    `tags: foo` would otherwise iterate character-by-character and silently scramble."""
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError(f"expected a list, got {type(value).__name__}")
    return tuple(str(item) for item in value)


def _as_opt_str(value: object) -> str | None:
    """An optional free-text field: absent -> None, a YAML scalar -> its string form, anything
    structured (list/dict) -> reject. Keeps a bad type from building a type-violating Article."""
    if value is None:
        return None
    if not isinstance(value, str | int | float):
        raise ValueError(f"expected a string, got {type(value).__name__}")
    return str(value)


def _as_opt_int(value: object) -> int | None:
    """An optional integer field: absent -> None, an int -> itself, anything else (incl. bool,
    float, str) -> reject rather than coerce."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected an integer, got {type(value).__name__}")
    return value


def _as_opt_edtf(value: object) -> EdtfDate | None:
    """An optional EDTF date field: absent -> None, a YAML scalar -> EdtfDate (validates eagerly),
    invalid EDTF string -> ValueError (caller wraps to ArchiveError)."""
    if value is None:
        return None
    if not isinstance(value, str | int | float):
        raise ValueError(f"date: expected a string, got {type(value).__name__}")
    return EdtfDate(str(value))


def _as_str_map(value: object) -> tuple[tuple[str, str], ...]:
    """Coerce the optional custom mapping to (str, str) pairs: absent -> empty, a non-mapping ->
    reject. Article.__post_init__ re-normalizes (sort, dedupe, reserved-key check)."""
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ValueError(f"custom: expected a mapping, got {type(value).__name__}")
    return tuple((str(key), str(val)) for key, val in value.items())


def _version_of(fm: dict[str, Any]) -> Version:
    """The stored optimistic-concurrency version: an exact non-negative int. Reject bool/float/
    str rather than coercing (int(1.5) -> 1 would silently accept a corrupt version)."""
    value = fm["version"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"version must be a non-negative integer, got {value!r}")
    return value


def _audience_from_front_matter(fm: dict[str, Any]) -> Audience | None:
    """Decode the optional audience. An absent or null key is inherit (None, ADR 0001);
    a present mapping is an explicit rung; anything else present is corrupt."""
    raw = fm.get("audience")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"audience: expected a mapping, got {type(raw).__name__}")
    if not raw:
        return None  # a content-less `audience: {}` names no rung -> inherit, like an absent key
    return Audience(
        tier=AudienceTier(raw.get("tier", AudienceTier.MEMBERS.value)),
        groups=_as_str_tuple(raw.get("groups")),
    )


def _article_from_front_matter(fm: dict[str, Any], body: str) -> Article:
    media = fm.get("media") or []
    if not isinstance(media, list | tuple):
        raise ValueError(f"media: expected a list, got {type(media).__name__}")
    return Article(
        ulid=str(fm["ulid"]),
        title=str(fm["title"]),
        collection_id=str(fm["collection_id"]),
        body=body,
        lifecycle=Lifecycle(fm["lifecycle"]),
        audience=_audience_from_front_matter(fm),
        ref_code=_as_opt_str(fm.get("ref_code")),
        media_type=_as_opt_str(fm.get("media_type")),
        document_type=_as_opt_str(fm.get("document_type")),
        tags=_as_str_tuple(fm.get("tags")),
        physical_location=_as_opt_str(fm.get("physical_location")),
        date=_as_opt_edtf(fm.get("date")),
        creator=_as_opt_str(fm.get("creator")),
        subject_place=_as_opt_str(fm.get("subject_place")),
        custom=_as_str_map(fm.get("custom")),
        media=tuple(
            MediaRef(
                filename=str(m["filename"]),
                content_hash=str(m["content_hash"]),
                media_type=_as_opt_str(m.get("media_type")),
                byte_size=_as_opt_int(m.get("byte_size")),
            )
            for m in media
        ),
    )
