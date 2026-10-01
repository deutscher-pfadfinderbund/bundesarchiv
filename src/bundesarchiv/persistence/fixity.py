"""The fixity check (ADR 0019 "Fixity"): the canonical tree against what its READMEs say.

`verify` reads every README version, current and history, of every Article and Collection,
re-hashes each media file a readable version names, and lists the stored files no version accounts
for. It writes nothing. Its keys come from their owners, `_writer` and `_layout`. It sees
what `ObjectStore.list` lists: reserved keys (`is_reserved`) are outside it.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from bundesarchiv.domain.models import MediaRef, Ulid
from bundesarchiv.persistence import collection_readme, readme
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS, content_digest, media_key
from bundesarchiv.persistence._writer import is_history_key
from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore

#: How the media files one README version names are read from its text.
type _MediaOf = Callable[[Ulid, str], tuple[MediaRef, ...]]


@dataclass(frozen=True, slots=True)
class Report:
    """What one check found, each finding a key: README versions that do not parse
    (`unreadable_readmes`); media files that cannot be read (`unreadable_files`); media files whose
    bytes do not hash to the `content_hash` of every version naming them (`altered`); media files a
    version names that are not stored (`missing`); stored files that are neither a README version
    nor a media file a readable version names (`unreferenced`). `readmes` and `media` count the
    versions read and the files re-hashed."""

    readmes: int
    media: int
    unreadable_readmes: tuple[str, ...]
    unreadable_files: tuple[str, ...]
    altered: tuple[str, ...]
    missing: tuple[str, ...]
    unreferenced: tuple[str, ...]

    @property
    def findings(self) -> int:
        unreadable = (self.unreadable_readmes, self.unreadable_files)
        return sum(map(len, (*unreadable, self.altered, self.missing, self.unreferenced)))


def verify(store: ObjectStore) -> Report:
    """Check the tree `store` holds. A save or a delete racing the check can show as a finding
    that the next check no longer reports."""
    stored = frozenset(store.list())
    versions: list[str] = []
    unreadable: list[str] = []
    named: defaultdict[str, set[str]] = defaultdict(set)
    for readme_key, ulid, folder, media_of in _records(stored):
        for key in (readme_key, *_history(store, folder)):
            versions.append(key)
            try:
                refs = media_of(ulid, store.read(key).decode("utf-8"))
            except ArchiveError, UnicodeDecodeError:
                unreadable.append(key)
                continue
            for ref in refs:
                named[media_key(ulid, ref)].add(ref.content_hash)
    read = dict(_hashes(store, sorted(named.keys() & stored)))
    hashed = {key: digest for key, digest in read.items() if digest is not None}
    return Report(
        readmes=len(versions),
        media=len(hashed),
        unreadable_readmes=tuple(unreadable),
        unreadable_files=tuple(key for key in read if key not in hashed),
        altered=tuple(key for key, digest in hashed.items() if named[key] != {digest}),
        missing=tuple(sorted(named.keys() - read.keys())),
        unreferenced=tuple(sorted(stored.difference(versions, named))),
    )


def _records(stored: Iterable[str]) -> Iterator[tuple[str, Ulid, str, _MediaOf]]:
    """Every Article and Collection with a README among `stored`: that key, the ulid, the folder,
    and how to read the media files a version names."""
    for key in sorted(stored):
        if ulid := ARTICLES.ulid_of_readme(key):
            yield key, ulid, ARTICLES.folder(ulid), _article_media
        elif ulid := COLLECTIONS.ulid_of_readme(key):
            yield key, ulid, COLLECTIONS.folder(ulid), _collection_media


def _history(store: ObjectStore, folder: str) -> list[str]:
    """The keys of `folder`'s history files."""
    return [key for key in store.list(f"{folder}/") if is_history_key(folder, key)]


def _article_media(ulid: Ulid, text: str) -> tuple[MediaRef, ...]:
    return readme.decode(ulid, text)[0].media


def _collection_media(ulid: Ulid, text: str) -> tuple[MediaRef, ...]:
    collection_readme.decode_collection(text, ulid=ulid)
    return ()


def _hashes(store: ObjectStore, keys: Iterable[str]) -> Iterator[tuple[str, str | None]]:
    """Each of `keys` with the sha256 of its bytes, or None when they cannot be read. A key that is
    gone by now is skipped. The read runs outside the adapter's error mapping, hence `OSError`."""
    for key in keys:
        try:
            with store.open_stream(key) as stream:
                digest: str | None = content_digest(stream)[0]
        except NotFound:
            continue
        except ArchiveError, OSError:
            digest = None
        yield key, digest
