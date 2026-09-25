"""ArticleRepository — the deep module the rest of the app uses (ADR 0005).

It owns the whole canonical-file protocol and sits on an injected `ObjectStore`:

    articles/<ulid>/README.md             the commit point (front-matter + body + marker)
    articles/<ulid>/history/<version>.md  each replaced README
    articles/<ulid>/media/<sha256>        content-addressed media blobs, write-once
    .trash/articles/<ulid>/...            recoverable destination for hard_delete (reserved)

The README.md ⇄ Article translation is the `readme` codec. The README and history keys and the save
order are `_writer.commit`'s; this module owns the rest of the key scheme, media write-once and
recoverable delete.

Callers depend only on this module; they never touch `ObjectStore` keys directly.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO

from bundesarchiv.domain.models import Article, MediaRef, Ulid, Version
from bundesarchiv.persistence import readme
from bundesarchiv.persistence._writer import commit, readme_key
from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore


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
            text = self._read_readme(ulid)
        except NotFound:
            raise NotFound(ulid) from None
        article, version = readme.decode(ulid, text)
        return Stored(article, version)

    def save(self, article: Article, expected_version: Version) -> Version:
        """Commit `article` as the version after `expected_version` and return it. Raises
        `Conflict` (writing nothing) on a stale version, `ArchiveError` on media not yet stored."""
        return commit(
            self._store,
            _folder(article.ulid),
            expected_version,
            version_of=lambda text: readme.read_version(article.ulid, text),
            render=lambda version: readme.encode(article, version),
            precondition=lambda: self._refuse_unstored_media(article),
        )

    def add_media(
        self,
        ulid: Ulid,
        filename: str,
        data: bytes,
        media_type: str | None = None,
        caption: str | None = None,
    ) -> MediaRef:
        """Store `data` content-addressed (write-once) and return a reference to embed
        in an Article before `save`. An optional `caption` (ADR 0015) is carried into the ref."""
        content_hash = hashlib.sha256(data).hexdigest()
        key = _media_key(ulid, content_hash)
        if not self._store.exists(key):  # write-once: identical bytes are idempotent
            self._store.write_atomic(key, data)
        return MediaRef(filename, content_hash, media_type, len(data), caption)

    def media_key(self, ulid: Ulid, content_hash: str) -> str:
        """The store-relative key of one media blob (`articles/<ulid>/media/<hash>`).

        THE layout authority (ADR 0005): a caller that must name a blob on the wire — the
        X-Accel redirect target nginx resolves (ADR 0017) — asks here instead of restating
        the scheme."""
        return _media_key(ulid, content_hash)

    def open_media(self, ulid: Ulid, content_hash: str) -> BinaryIO:
        """A readable stream over one Article's media blob, for a caller that hands the bytes
        straight on without materializing them (the dev media response). Raises `NotFound` if
        the blob is not stored; the caller closes the stream."""
        return self._store.open_stream(_media_key(ulid, content_hash))

    def find_blob(self, content_hash: str) -> bytes | None:
        """The bytes of ANY stored media blob with `content_hash`, or None if none is stored.

        Media is content-addressed and write-once, so identical bytes may hang off several
        Articles and every match is equivalent — a job deriving an artifact from the bytes
        (the thumbnailer) needs no Article. Walks the article tree: there is no hash→key index,
        and building one would be a second source of truth about where blobs are."""
        suffix = f"/{_MEDIA_SEGMENT}/{content_hash}"
        key = next((k for k in self._store.list(f"{_ROOT}/") if k.endswith(suffix)), None)
        return None if key is None else self._store.read(key)

    def list_ulids(self) -> Iterable[Ulid]:
        return [ulid for key in self._store.list(f"{_ROOT}/") if (ulid := _ulid_of_readme(key))]

    def keys_for(self, ulid: Ulid) -> list[str]:
        """The live canonical keys under this Article's tree (README, history, media), for callers
        that must address them by key without hand-rolling the layout — e.g. the mirror replay, which
        enqueues one push per key. Reserved keys are excluded by `list`. An absent Article yields
        ``[]``."""
        return list(self._store.list(f"{_folder(ulid)}/"))

    def hard_delete(self, ulid: Ulid) -> None:
        """Move the Article's whole tree into recoverable trash (reserved, excluded
        from listings), then remove the originals. A no-op if the Article is absent.

        Not atomic (the port has no batch move): a crash mid-copy leaves the originals intact
        with a partial trash copy; a crash mid-delete leaves a complete trash copy with the
        originals partly gone. The copy-all-then-delete-all order keeps the data recoverable
        across either window. Reads each blob fully into memory — fine at v1 media sizes."""
        keys = self.keys_for(ulid)
        for key in keys:
            self._store.write_atomic(f".trash/{key}", self._store.read(key))
        for key in keys:
            self._store.delete(key)

    def _refuse_unstored_media(self, article: Article) -> None:
        for ref in article.media:
            if not self._store.exists(_media_key(article.ulid, ref.content_hash)):
                raise ArchiveError(
                    f"{article.ulid}: media {ref.content_hash} not stored before save"
                )

    def _read_readme(self, ulid: Ulid) -> str:
        """Read + decode the Article's README text (raises NotFound if absent)."""
        return self._store.read(_readme_key(ulid)).decode("utf-8")


# --- key scheme ------------------------------------------------------------------

#: The path segment that marks a key as a media blob — the half of the media layout
#: `find_blob` matches on when it has a hash but no ulid.
_MEDIA_SEGMENT = "media"

_ROOT = "articles"


def _folder(ulid: Ulid) -> str:
    return f"{_ROOT}/{ulid}"


def _readme_key(ulid: Ulid) -> str:
    return readme_key(_folder(ulid))


def _media_key(ulid: Ulid, content_hash: str) -> str:
    return f"{_folder(ulid)}/{_MEDIA_SEGMENT}/{content_hash}"


def _ulid_of_readme(key: str) -> Ulid | None:
    parts = key.split("/")
    return parts[1] if len(parts) == 3 and key == _readme_key(parts[1]) else None
