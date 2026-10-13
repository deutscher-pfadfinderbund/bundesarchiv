"""README codec (ADR 0005, ADR 0006). Only `UnreadableReadme` crosses out."""

from datetime import datetime
from typing import Any

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Change,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.persistence import _change, _front_matter
from bundesarchiv.persistence.errors import UnreadableReadme


def encode(article: Article, version: Version, change: Change) -> str:
    """Empty optional fields are omitted (ADR 0015)."""
    front_matter = {
        "ulid": article.ulid,
        "version": version,
        **_change.to_front_matter(change),
        "title": article.title,
        "collection_id": article.collection_id,
        "lifecycle": article.lifecycle.value,
        **(_change.to_front_matter(article.deleted, "deleted") if article.deleted else {}),
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
        **({"ref_code": article.ref_code} if article.ref_code is not None else {}),
        **({"media_type": article.media_type} if article.media_type is not None else {}),
        **({"document_type": article.document_type} if article.document_type is not None else {}),
        **({"tags": list(article.tags)} if article.tags else {}),
        **(
            {"physical_location": article.physical_location}
            if article.physical_location is not None
            else {}
        ),
        **({"date": article.date.value} if article.date is not None else {}),
        **({"creator": article.creator} if article.creator is not None else {}),
        **({"subject_place": article.subject_place} if article.subject_place is not None else {}),
        **({"media": [_media_entry(m) for m in article.media]} if article.media else {}),
        **({"custom": dict(article.custom)} if article.custom else {}),
        **(
            {"added_at": _change.utc_text(article.added_at)} if article.added_at is not None else {}
        ),
        **({"template": True} if article.template else {}),
    }
    return _front_matter.dump(front_matter, article.body)


def _media_entry(media: MediaRef) -> dict[str, Any]:
    entry: dict[str, Any] = {"filename": media.filename}
    if media.stored_name is not None:
        entry["stored_name"] = media.stored_name
    entry["content_hash"] = media.content_hash
    if media.media_type is not None:
        entry["media_type"] = media.media_type
    if media.byte_size is not None:
        entry["byte_size"] = media.byte_size
    if media.caption is not None:
        entry["caption"] = media.caption
    if media.alt is not None:
        entry["alt"] = media.alt
    return entry


def decode(ulid: Ulid, text: str) -> tuple[Article, Version, Change | None]:
    """Parse README.md text back to its Article, stored version and change record (None for a
    README written before ADR 0019)."""
    front_matter, body = _front_matter.parse(ulid, text)
    try:
        return (
            _article_from_front_matter(front_matter, body),
            _front_matter.version_of(front_matter),
            _change.from_front_matter(front_matter),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise UnreadableReadme(f"{ulid}: README front-matter is malformed: {exc}") from exc


def read_version(ulid: Ulid, text: str) -> Version:
    front_matter, _ = _front_matter.parse(ulid, text)
    try:
        return _front_matter.version_of(front_matter)
    except (KeyError, ValueError, TypeError) as exc:
        raise UnreadableReadme(f"{ulid}: README version is malformed: {exc}") from exc


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


def _as_flag(value: object) -> bool:
    """An optional mark: absent -> False, a YAML boolean -> itself, anything else -> reject."""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"expected true or false, got {type(value).__name__}")
    return value


def _as_opt_edtf(value: object) -> EdtfDate | None:
    """An optional EDTF date field: absent -> None, a YAML scalar -> EdtfDate (validates eagerly),
    invalid EDTF string -> ValueError (caller wraps to UnreadableReadme)."""
    if value is None:
        return None
    if not isinstance(value, str | int | float):
        raise ValueError(f"date: expected a string, got {type(value).__name__}")
    return EdtfDate(str(value))


def _as_opt_instant(value: object) -> datetime | None:
    """An optional UTC instant: absent -> None, ISO 8601 text -> datetime (Article checks UTC and
    whole seconds), anything else — incl. an unquoted YAML timestamp — -> reject."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"expected an ISO 8601 text, got {type(value).__name__}")
    return datetime.fromisoformat(value)


def _as_str_map(value: object) -> tuple[tuple[str, str], ...]:
    """Coerce the optional custom mapping to (str, str) pairs: absent -> empty, a non-mapping ->
    reject. Article.__post_init__ re-normalizes (sort, dedupe, reserved-key check)."""
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ValueError(f"custom: expected a mapping, got {type(value).__name__}")
    return tuple((str(key), str(val)) for key, val in value.items())


def audience_from_front_matter(fm: dict[str, Any]) -> Audience | None:
    """Decode the optional audience of an Article or a Collection front matter. An absent or null
    key is inherit (None, ADR 0001); a present mapping is an explicit rung; anything else present
    is corrupt (`ValueError`)."""
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
        audience=audience_from_front_matter(fm),
        ref_code=_as_opt_str(fm.get("ref_code")),
        media_type=_as_opt_str(fm.get("media_type")),
        document_type=_as_opt_str(fm.get("document_type")),
        tags=_as_str_tuple(fm.get("tags")),
        physical_location=_as_opt_str(fm.get("physical_location")),
        date=_as_opt_edtf(fm.get("date")),
        creator=_as_opt_str(fm.get("creator")),
        subject_place=_as_opt_str(fm.get("subject_place")),
        custom=_as_str_map(fm.get("custom")),
        added_at=_as_opt_instant(fm.get("added_at")),
        deleted=_change.from_front_matter(fm, "deleted"),
        template=_as_flag(fm.get("template")),
        media=tuple(
            MediaRef(
                filename=str(m["filename"]),
                content_hash=str(m["content_hash"]),
                media_type=_as_opt_str(m.get("media_type")),
                byte_size=_as_opt_int(m.get("byte_size")),
                caption=_as_opt_str(m.get("caption")),
                alt=_as_opt_str(m.get("alt")),
                stored_name=_as_opt_str(m.get("stored_name")),
            )
            for m in media
        ),
    )
