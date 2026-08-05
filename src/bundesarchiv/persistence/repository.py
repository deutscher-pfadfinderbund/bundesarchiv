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
v1, ADR 0013).
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from bundesarchiv.domain.models import Article, MediaRef, Ulid, Version
from bundesarchiv.persistence import readme
from bundesarchiv.persistence._writer import WRITER_LOCK
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
        # CONCURRENCY (ADR 0013): the version check-then-write is CAS, and the ObjectStore port
        # has no native compare-and-swap, so the whole load-check-write critical section runs
        # under the ONE process-wide WRITER_LOCK shared with CollectionRepository (both write the
        # same store — see persistence/_writer.py). That serialization is what makes check-then-
        # write atomic within the single app process: two genuinely-interleaved saves can no
        # longer both pass the check; the second sees the bumped version and raises Conflict, the
        # write-nothing failure mode a stale form save relies on. The cross-process race is out of
        # scope by the single-app-process deploy rule (ADR 0013 runbook item); a second writer
        # host would need real distributed CAS (deferred with a trigger).
        with WRITER_LOCK:
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
        `NotFound` if absent. `mutate` must not add media (use add_media + save).

        WARNING — internal idempotent mutations ONLY (worker jobs, migrations, ADR 0013).
        Because it re-loads and retries on `Conflict`, this is last-writer-wins by
        construction: a retry re-applies `mutate` to the WINNER's fresh Article, so the
        concurrent edit is not lost — but only when `mutate` is a pure, idempotent
        transform of whatever it is handed. It is FORBIDDEN for web form saves: a form
        carries a value the archivist typed against a now-stale Article, so retrying
        would silently overwrite the concurrent edit with that stale form (silent
        last-writer-wins — the one unforgivable archive failure). Form saves call
        `save(mutated, expected_version_from_form)` directly and let the FIRST `Conflict`
        propagate to the re-load/re-apply UI."""
        while True:
            stored = self.load(ulid)
            try:
                return self.save(mutate(stored.article), stored.version)
            except Conflict:
                retries -= 1
                if retries < 0:
                    raise

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

    def list_ulids(self) -> Iterable[Ulid]:
        return [ulid for key in self._store.list("articles/") if (ulid := _ulid_of_readme(key))]

    def keys_for(self, ulid: Ulid) -> list[str]:
        """The live canonical keys under this Article's tree (README + media + changes), for callers
        that must address them by key without hand-rolling the layout — e.g. the mirror replay, which
        enqueues one push per key. Reserved keys (temp/lock/snapshots) are excluded by `list`. An
        absent Article yields ``[]``."""
        return list(self._store.list(f"articles/{ulid}/"))

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
