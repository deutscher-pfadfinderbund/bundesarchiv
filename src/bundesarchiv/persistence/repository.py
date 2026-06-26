"""ArticleRepository — the deep module the rest of the app uses (ADR 0005).

It owns the whole canonical-file protocol and sits on an injected `ObjectStore`:

    articles/<ulid>/README.md          the commit point (front-matter + body + marker)
    articles/<ulid>/media/<sha256>     content-addressed media blobs, write-once
    articles/<ulid>/changes/<version>.json   append-only change records
    .trash/<ulid>/...                  recoverable destination for hard_delete (reserved)

`save` is optimistic: the README front-matter carries a `version`; a stale
`expected_version` raises `Conflict`. The pinned write order is media → README
(= commit) → changes: a half-written save leaves the prior README (or none), and a
README is refused if it references media not yet stored.

Callers depend only on this module; they never touch `ObjectStore` keys directly.
Snapshots (.snapshots/) and the per-Article lock object are deferred (single-writer
v1); see docs/plans/part-1-persistence.md.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import yaml

from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.persistence.errors import ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore

_MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->"
_FENCE = "---"


@dataclass(frozen=True, slots=True)
class Stored:
    """An Article as loaded, paired with the version to pass to the next `save`.
    (`load` returns this rather than a bare Article so optimistic concurrency works.)"""

    article: Article
    version: Version


class ArticleRepository:
    """Loads and saves Articles as the canonical articles/<ulid>/ tree on an
    `ObjectStore`."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def load(self, ulid: Ulid) -> Stored:
        try:
            text = self._store.read(_readme_key(ulid)).decode("utf-8")
        except NotFound:
            raise NotFound(ulid) from None
        article, version = _parse_readme(ulid, text)
        return Stored(article, version)

    def save(self, article: Article, expected_version: Version) -> Version:
        current = self._current_version(article.ulid)
        if current != expected_version:
            raise Conflict(
                f"{article.ulid}: expected version {expected_version}, store has {current}"
            )
        # Pinned order: media must already be stored before the README commits to it.
        for ref in article.media:
            if not self._store.exists(_media_key(article.ulid, ref.content_hash)):
                raise ArchiveError(
                    f"{article.ulid}: media {ref.content_hash} not stored before save"
                )
        new_version = current + 1
        self._store.write_atomic(
            _readme_key(article.ulid), _render_readme(article, new_version).encode("utf-8")
        )  # the commit
        self._store.write_atomic(
            _changes_key(article.ulid, new_version),
            json.dumps({"ulid": article.ulid, "version": new_version}, sort_keys=True).encode(),
        )
        return new_version

    def add_media(
        self, ulid: Ulid, filename: str, data: bytes, media_type: str | None = None
    ) -> MediaRef:
        """Store `data` content-addressed (write-once) and return a reference to embed
        in an Article before `save`."""
        content_hash = hashlib.sha256(data).hexdigest()
        key = _media_key(ulid, content_hash)
        if not self._store.exists(key):  # write-once: identical bytes are idempotent
            self._store.write_atomic(key, data)
        return MediaRef(filename, content_hash, media_type, len(data))

    def list_ulids(self) -> Iterable[Ulid]:
        return [ulid for key in self._store.list("articles/") if (ulid := _ulid_of_readme(key))]

    def hard_delete(self, ulid: Ulid) -> None:
        """Move the Article's whole tree into recoverable trash (reserved, excluded
        from listings), then remove the originals. A no-op if the Article is absent."""
        keys = list(self._store.list(f"articles/{ulid}/"))
        for key in keys:
            self._store.write_atomic(f".trash/{key}", self._store.read(key))
        for key in keys:
            self._store.delete(key)

    def _current_version(self, ulid: Ulid) -> Version:
        try:
            text = self._store.read(_readme_key(ulid)).decode("utf-8")
        except NotFound:
            return 0
        return _parse_readme(ulid, text)[1]


# --- key scheme ------------------------------------------------------------------


def _readme_key(ulid: Ulid) -> str:
    return f"articles/{ulid}/README.md"


def _media_key(ulid: Ulid, content_hash: str) -> str:
    return f"articles/{ulid}/media/{content_hash}"


def _changes_key(ulid: Ulid, version: Version) -> str:
    return f"articles/{ulid}/changes/{version}.json"


def _ulid_of_readme(key: str) -> Ulid | None:
    # "articles/<ulid>/README.md" -> "<ulid>"; anything else (media, changes) -> None
    parts = key.split("/")
    if len(parts) == 3 and parts[0] == "articles" and parts[2] == "README.md":
        return parts[1]
    return None


# --- README (de)serialization ----------------------------------------------------


def _render_readme(article: Article, version: Version) -> str:
    front_matter = {
        "ulid": article.ulid,
        "version": version,
        "title": article.title,
        "collection_id": article.collection_id,
        "lifecycle": article.lifecycle.value,
        "audience": {"tier": article.audience.tier.value, "groups": list(article.audience.groups)},
        "ref_code": article.ref_code,
        "media_type": article.media_type,
        "document_type": article.document_type,
        "tags": list(article.tags),
        "physical_location": article.physical_location,
        "physical_description": article.physical_description,
        "media": [
            {
                "filename": m.filename,
                "content_hash": m.content_hash,
                "media_type": m.media_type,
                "byte_size": m.byte_size,
            }
            for m in article.media
        ],
    }
    yaml_block = yaml.safe_dump(
        front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip("\n")
    return f"{_MARKER}\n{_FENCE}\n{yaml_block}\n{_FENCE}\n{article.body}"


def _parse_readme(ulid: Ulid, text: str) -> tuple[Article, Version]:
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
    # lines[close + 1:] reconstructs the body verbatim (no stripping — a body may
    # legitimately open with blank lines).
    body = "\n".join(lines[close + 1 :])
    try:
        front_matter = yaml.safe_load("\n".join(lines[1:close]))
        if not isinstance(front_matter, dict):
            raise ArchiveError(f"{ulid}: README front-matter is not a mapping")
        return _article_from_front_matter(front_matter, body), int(front_matter["version"])
    except (KeyError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise ArchiveError(f"{ulid}: README front-matter is malformed: {exc}") from exc


def _as_str_tuple(value: object) -> tuple[str, ...]:
    """Coerce a front-matter list to a tuple of strings, rejecting a scalar — a bare
    `tags: foo` would otherwise iterate character-by-character and silently scramble."""
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError(f"expected a list, got {type(value).__name__}")
    return tuple(str(item) for item in value)


def _article_from_front_matter(fm: dict[str, Any], body: str) -> Article:
    audience = fm.get("audience") or {}
    media = fm.get("media") or []
    if not isinstance(media, list | tuple):
        raise ValueError(f"media: expected a list, got {type(media).__name__}")
    return Article(
        ulid=str(fm["ulid"]),
        title=str(fm["title"]),
        collection_id=str(fm["collection_id"]),
        body=body,
        lifecycle=Lifecycle(fm["lifecycle"]),
        audience=Audience(
            tier=AudienceTier(audience.get("tier", AudienceTier.MEMBERS.value)),
            groups=_as_str_tuple(audience.get("groups")),
        ),
        ref_code=fm.get("ref_code"),
        media_type=fm.get("media_type"),
        document_type=fm.get("document_type"),
        tags=_as_str_tuple(fm.get("tags")),
        physical_location=fm.get("physical_location"),
        physical_description=fm.get("physical_description"),
        media=tuple(
            MediaRef(
                filename=str(m["filename"]),
                content_hash=str(m["content_hash"]),
                media_type=m.get("media_type"),
                byte_size=m.get("byte_size"),
            )
            for m in media
        ),
    )
