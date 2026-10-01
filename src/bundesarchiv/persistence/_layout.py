"""Where a record's files sit in the canonical tree (ADR 0005, ADR 0019 "Fixity").

    articles/<ulid>/README.md       collections/<ulid>/README.md
    articles/<ulid>/media/<name>

The keys inside a folder beyond the README (``history/``) and the save order are ``_writer``'s.
Both repositories and the fixity check read the layout from here.
"""

import hashlib
from dataclasses import dataclass
from typing import BinaryIO

from bundesarchiv.domain.models import MediaRef, Ulid
from bundesarchiv.persistence._writer import readme_key
from bundesarchiv.persistence.objectstore import ObjectStore


@dataclass(frozen=True, slots=True)
class Records:
    """One kind of record: every record is the folder ``<root>/<ulid>``."""

    root: str

    def folder(self, ulid: Ulid) -> str:
        return f"{self.root}/{ulid}"

    def readme_key(self, ulid: Ulid) -> str:
        return readme_key(self.folder(ulid))

    def ulid_of_readme(self, key: str) -> Ulid | None:
        """The ulid whose README `key` is, or None when `key` is no README of this kind."""
        parts = key.split("/")
        return parts[1] if len(parts) == 3 and key == self.readme_key(parts[1]) else None

    def list_ulids(self, store: ObjectStore) -> list[Ulid]:
        """The ulid of every record with a README in `store`, none of them read."""
        return [ulid for key in store.list(f"{self.root}/") if (ulid := self.ulid_of_readme(key))]


ARTICLES = Records("articles")
COLLECTIONS = Records("collections")


def media_folder(ulid: Ulid) -> str:
    return f"{ARTICLES.folder(ulid)}/media/"


def media_key(ulid: Ulid, ref: MediaRef) -> str:
    return f"{media_folder(ulid)}{ref.filename if ref.stored_name is None else ref.stored_name}"


#: How much of a media file one read of a hash pass takes.
_CHUNK = 1024 * 1024


def content_digest(stream: BinaryIO) -> tuple[str, int]:
    """The sha256 hex digest and the byte count of what `stream` holds from where it stands."""
    sha256 = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK):
        sha256.update(chunk)
        size += len(chunk)
    return sha256.hexdigest(), size
