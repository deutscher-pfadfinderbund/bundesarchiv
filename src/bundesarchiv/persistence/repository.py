"""ArticleRepository — the deep module the rest of the app uses (ADR 0005).

It owns the whole canonical-file protocol and sits on an injected `ObjectStore`:

    articles/<ulid>/README.md             the commit point (front-matter + body + marker)
    articles/<ulid>/history/<version>.md  each replaced README
    articles/<ulid>/media/<name>          media files under their own name, write-once

The README.md ⇄ Article translation is the `readme` codec. The README and history keys and the save
order are `_writer.commit`'s; this module owns the rest of the key scheme, the media names (ADR
0019 "Media names") and the hard delete.

Callers depend only on this module; they never touch `ObjectStore` keys directly.
"""

import hashlib
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO

from bundesarchiv.domain.models import Article, Change, MediaRef, Ulid, Version
from bundesarchiv.persistence import readme
from bundesarchiv.persistence._writer import StoredKey, commit, keys_in_save_order, readme_key
from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore

__all__ = ["ArticleRepository", "Stored", "StoredKey", "cleaned_name"]


@dataclass(frozen=True, slots=True)
class Stored:
    """An Article as loaded, paired with the version to pass to the next `save` and that version's
    change record (None for a README written before ADR 0019)."""

    article: Article
    version: Version
    change: Change | None


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
        article, version, change = readme.decode(ulid, text)
        return Stored(article, version, change)

    def save(self, article: Article, expected_version: Version, *, changed_by: str) -> Version:
        """Commit `article` as the version after `expected_version`, by `changed_by`, and return
        it. Raises `Conflict` (writing nothing) on a stale version, `ArchiveError` on media not yet
        stored."""
        return commit(
            self._store,
            _folder(article.ulid),
            expected_version,
            changed_by=changed_by,
            version_of=lambda text: readme.read_version(article.ulid, text),
            render=lambda version, change: readme.encode(article, version, change),
            precondition=lambda: self._refuse_unstored_media(article),
        )

    def add_media(
        self,
        ulid: Ulid,
        filename: str,
        source: BinaryIO,
        media_type: str | None = None,
        caption: str | None = None,
    ) -> MediaRef:
        """Store what `source` holds, from where it stands to its end, as one of the Article's
        media files under `filename` cleaned (ADR 0019 "Media names"), and return the reference to
        embed in the Article before `save`. An optional `caption` (ADR 0015) is carried into the
        ref. Raises `ValueError`, writing nothing, when `cleaned_name(filename)` is None.

        `source` is read in chunks, once to hash it and once to store it (ADR 0019 "Streaming
        upload"), so it must be seekable; no step holds the whole file in memory."""
        name = _clean(filename)
        if not name:
            raise ValueError(f"nothing is left of the media name {filename!r} once cleaned")
        start = source.tell()
        content_hash, size = digest = _digest(source)
        stored = self._place(ulid, name, source, start, digest)
        return MediaRef(
            filename,
            content_hash,
            media_type,
            size,
            caption,
            stored_name=None if stored == filename else stored,
        )

    def media_key(self, ulid: Ulid, ref: MediaRef) -> str:
        """The store-relative key of `ref`'s file (`articles/<ulid>/media/<name>`).

        THE layout authority (ADR 0005): a caller that must name a file on the wire — the
        X-Accel redirect target nginx resolves (ADR 0017) — asks here instead of restating
        the scheme."""
        return _media_key(ulid, ref)

    def open_media(self, ulid: Ulid, ref: MediaRef) -> BinaryIO:
        """A readable stream over `ref`'s file, for a caller that hands the bytes straight on
        without materializing them. Raises `NotFound` if the file is not stored; the caller
        closes the stream."""
        return self._store.open_stream(_media_key(ulid, ref))

    def list_ulids(self) -> Iterable[Ulid]:
        return [ulid for key in self._store.list(f"{_ROOT}/") if (ulid := _ulid_of_readme(key))]

    def keys_for(self, ulid: Ulid) -> list[StoredKey]:
        """The keys of the Article's folder in the order a save writes them: media, history, the
        README last (ADR 0020 push order). A media file the current README names carries its
        `content_hash`; a README that does not decode is not `readable`. Reserved keys are excluded
        by `list`. An absent Article yields ``[]``."""
        named = self._named_media(ulid)
        return keys_in_save_order(
            self._store, _folder(ulid), named or {}, readable=named is not None
        )

    def hard_delete(self, ulid: Ulid) -> None:
        """Remove the Article's folder for good, keeping no copy (ADR 0020). A no-op if the
        Article is absent."""
        self._store.delete_prefix(_folder(ulid))

    def _place(
        self, ulid: Ulid, name: str, source: BinaryIO, start: int, digest: tuple[str, int]
    ) -> str:
        """The name in the Article's media folder that ends up holding the bytes `source` holds
        from `start` on (`digest` is their hash and size): the first of `name`'s candidates that is
        free, created there, or that already holds these bytes, reused. Takes no lock (ADR 0019):
        a create that loses a race is checked like a taken name."""
        content_hash, size = digest
        folder = _media_folder(ulid)
        taken = {_fold(_name_of(entry.key)): entry for entry in self._store.list_entries(folder)}
        for candidate in _candidates(name, content_hash):
            entry = taken.get(_fold(candidate))
            if entry is None:
                key = f"{folder}{candidate}"
                source.seek(start)
                try:
                    self._store.create_large(key, source, size)
                    return candidate
                except AlreadyExists:
                    holder = key
            elif entry.size == size:
                holder = entry.key
            else:
                continue
            with self._store.open_stream(holder) as stored:
                if _digest(stored) == digest:
                    return _name_of(holder)
        raise ArchiveError(f"{folder}: every candidate name holds other bytes")

    def _named_media(self, ulid: Ulid) -> dict[str, str] | None:
        """The key and `content_hash` of each media file the current README names, or None when
        that README does not decode."""
        try:
            media = self.load(ulid).article.media
        except NotFound:
            return {}
        except ArchiveError, UnicodeDecodeError:
            return None
        return {_media_key(ulid, ref): ref.content_hash for ref in media}

    def _refuse_unstored_media(self, article: Article) -> None:
        for ref in article.media:
            if not self._store.exists(_media_key(article.ulid, ref)):
                raise ArchiveError(
                    f"{article.ulid}: media {ref.content_hash} not stored before save"
                )

    def _read_readme(self, ulid: Ulid) -> str:
        """Read + decode the Article's README text (raises NotFound if absent)."""
        return self._store.read(_readme_key(ulid)).decode("utf-8")


# --- key scheme ------------------------------------------------------------------

_ROOT = "articles"


def _folder(ulid: Ulid) -> str:
    return f"{_ROOT}/{ulid}"


def _readme_key(ulid: Ulid) -> str:
    return readme_key(_folder(ulid))


def _media_folder(ulid: Ulid) -> str:
    return f"{_folder(ulid)}/media/"


def _media_key(ulid: Ulid, ref: MediaRef) -> str:
    return f"{_media_folder(ulid)}{ref.filename if ref.stored_name is None else ref.stored_name}"


def _name_of(key: str) -> str:
    return key.rpartition("/")[2]


def _ulid_of_readme(key: str) -> Ulid | None:
    parts = key.split("/")
    return parts[1] if len(parts) == 3 and key == _readme_key(parts[1]) else None


# --- media names (ADR 0019) ------------------------------------------------------

#: The longest name the StorageShare accepts, in bytes of UTF-8.
_NAME_MAX_BYTES = 250
_UNSAFE = frozenset('/\\:*?"<>|')
#: A longer extension would leave the stem no character (up to 4 bytes) beside the full-hash
#: suffix, so it counts as part of the stem.
_EXT_MAX_BYTES = _NAME_MAX_BYTES - len(".") - 64 - 4


def cleaned_name(filename: str) -> str | None:
    """The name a file uploaded as `filename` is stored under while that name is free (ADR 0019
    "Media names"), or None when nothing is left of it — a name to refuse, never to rename."""
    name = _clean(filename)
    return _fit(*_split(name)) if name else None


def _clean(filename: str) -> str:
    replaced = (
        "_" if ch in _UNSAFE or unicodedata.category(ch) in ("Cc", "Cs") else ch
        for ch in unicodedata.normalize("NFC", filename)
    )
    return "".join(replaced).strip(" .")


def _split(name: str) -> tuple[str, str]:
    """`name` as stem and extension (with its dot, or empty)."""
    stem, dot, ext = name.rpartition(".")
    if not dot or len(f"{dot}{ext}".encode()) > _EXT_MAX_BYTES:
        return name, ""
    return stem, f"{dot}{ext}"


def _fit(stem: str, ext: str, suffix: str = "") -> str:
    """`stem` + `suffix` + `ext`, the stem cut at a character boundary so the name fits
    `_NAME_MAX_BYTES`. The cut never ends the stem in a space or a dot."""
    budget = _NAME_MAX_BYTES - len(f"{suffix}{ext}".encode())
    if len(stem.encode()) > budget:
        stem = stem.encode()[:budget].decode(errors="ignore").rstrip(" .")
    return f"{stem}{suffix}{ext}"


def _candidates(name: str, content_hash: str) -> Iterator[str]:
    """The names to try for the cleaned `name`, in order: itself, `<stem>.<hash8>.<ext>`, and the
    same with the full hash."""
    stem, ext = _split(name)
    for suffix in ("", f".{content_hash[:8]}", f".{content_hash}"):
        yield _fit(stem, ext, suffix)


def _fold(name: str) -> str:
    """The form two names are compared in: Unicode canonical caseless matching."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


#: How much of a media file one read of a hash pass takes.
_CHUNK = 1024 * 1024


def _digest(stream: BinaryIO) -> tuple[str, int]:
    """The sha256 hex digest and the byte count of what `stream` holds from where it stands."""
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size
