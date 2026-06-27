"""ArticleRepository — the deep module the rest of the app uses (ADR 0005).

It owns the whole canonical-file protocol and sits on an injected `ObjectStore`:

    articles/<ulid>/README.md          the commit point (front-matter + body + marker)
    articles/<ulid>/media/<sha256>     content-addressed media blobs, write-once
    articles/<ulid>/changes/<version>.json   append-only change records
    .trash/articles/<ulid>/...         recoverable destination for hard_delete (reserved)

The README.md ⇄ Article translation is the `readme` codec; this module owns versioning,
the pinned write order, media write-once, and recoverable delete.

`save` is optimistic: the README front-matter carries a `version`; a stale
`expected_version` raises `Conflict`. The pinned write order is media → README
(= commit) → changes: a half-written save leaves the prior README (or none), and a
README is refused if it references media not yet stored. A failure *after* the README
commits (e.g. writing the changes record) still propagates, but the Article is by then
durably saved at the new version — the changes log is secondary metadata that ADR 0005
tolerates gaps in, and a caller's retry with the old version will surface `Conflict`,
signalling the save took effect.

Callers depend only on this module; they never touch `ObjectStore` keys directly.
Snapshots (.snapshots/) and the per-Article lock object are deferred (single-writer
v1); see docs/plans/part-1-persistence.md.
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from bundesarchiv.domain.models import Article, MediaRef, Ulid, Version
from bundesarchiv.persistence import readme
from bundesarchiv.persistence.errors import ArchiveError, Conflict, NotFound
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
        # CONCURRENCY LIMITATION (v1): this version check-then-write is NOT atomic, and the
        # ObjectStore port has no compare-and-swap. It is safe only under the single-writer
        # invariant (ADR 0002) — two genuinely-interleaved saves can both pass this check and
        # the second silently clobbers the first. The durable per-Article lock object (or a
        # CAS primitive on the port) that would close this is deferred; gate the Part-3/4
        # multi-writer paths (background worker, multi-process WSGI) on it.
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
            _readme_key(article.ulid), readme.encode(article, new_version).encode("utf-8")
        )  # the commit
        self._store.write_atomic(
            _changes_key(article.ulid, new_version),
            json.dumps({"ulid": article.ulid, "version": new_version}, sort_keys=True).encode(),
        )
        return new_version

    def update(
        self, ulid: Ulid, mutate: Callable[[Article], Article], *, retries: int = 3
    ) -> Version:
        """Load the Article, apply `mutate`, and save at its current version — the
        optimistic-concurrency dance hidden from callers, retrying on `Conflict` (a
        concurrent write) up to `retries` times. Returns the new version; raises
        `NotFound` if absent. `mutate` must not add media (use add_media + save)."""
        while True:
            stored = self.load(ulid)
            try:
                return self.save(mutate(stored.article), stored.version)
            except Conflict:
                retries -= 1
                if retries < 0:
                    raise

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
        from listings), then remove the originals. A no-op if the Article is absent.

        Not atomic (the port has no batch move): a crash mid-copy leaves the originals intact
        with a partial trash copy; a crash mid-delete leaves a complete trash copy with the
        originals partly gone. The copy-all-then-delete-all order keeps the data recoverable
        across either window. Reads each blob fully into memory — fine at v1 media sizes."""
        keys = list(self._store.list(f"articles/{ulid}/"))
        for key in keys:
            self._store.write_atomic(f".trash/{key}", self._store.read(key))
        for key in keys:
            self._store.delete(key)

    def _current_version(self, ulid: Ulid) -> Version:
        try:
            text = self._read_readme(ulid)
        except NotFound:
            return 0
        return readme.read_version(ulid, text)

    def _read_readme(self, ulid: Ulid) -> str:
        """Read + decode the Article's README text (raises NotFound if absent)."""
        return self._store.read(_readme_key(ulid)).decode("utf-8")


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
