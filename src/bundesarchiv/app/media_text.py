"""The page text of media files, read once per file into ``MediaText`` (ADR 0023).

v1 reads the text layer of PDFs (``pdf.page_texts``). A hash with rows counts as done; a file that
gave nothing usable stores the page-0 marker, so it counts as done too. Only a failed read or bytes
that do not match their hash leave no rows, and the next fill tries again. A file's bytes are
untrusted: no content problem raises past ``fill``.

``readable`` and ``parse`` decide; ``read``, ``record``, ``fill`` and ``missing`` touch the archive
and the rows.
"""

import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import assert_never

from bundesarchiv.app import pdf
from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import ULID, MediaRef
from bundesarchiv.index import indexer
from bundesarchiv.index.query import FileKind
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.repository import content_digest

logger = logging.getLogger(__name__)

#: Pages past this are never read; the longest legacy PDF has 365 pages (2026-10-11).
#: A change ships with a data migration that empties ``MediaText`` (ADR 0023).
MAX_PAGES = 2000


@dataclass(frozen=True, slots=True)
class Pages:
    """The text of each page, page 1 first (``""`` for a page without a text layer)."""

    texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Unreadable:
    """A file the reader cannot open (broken, encrypted, no pages): stored as the page-0 marker."""


@dataclass(frozen=True, slots=True)
class HashMismatch:
    """Bytes that are not the file their hash names: nothing is stored (ADR 0023)."""


type Parsed = Pages | Unreadable | HashMismatch


def reads(ref: MediaRef) -> bool:
    """Whether text is derived from ``ref``'s file."""
    return indexer.file_kind(ref) is FileKind.PDF


def readable(media: Iterable[MediaRef]) -> tuple[MediaRef, ...]:
    """The files of ``media`` that text is read from (``reads``), one per content hash."""
    return tuple({r.content_hash: r for r in media if reads(r)}.values())


def parse(data: bytes, content_hash: str) -> Parsed:
    """What the file ``data``, claimed to have ``content_hash``, gives (text is found by hash)."""
    if content_digest(io.BytesIO(data))[0] != content_hash:
        return HashMismatch()
    texts = pdf.page_texts(data, max_pages=MAX_PAGES)
    return Pages(texts) if texts else Unreadable()


def read(archive: Archive, ulid: ULID, ref: MediaRef) -> Parsed | None:
    """What Article ``ulid``'s file ``ref`` gives (``parse``), or None when the file is gone or its
    read fails (logged); a later fill tries again. Never raises for the file's bytes."""
    try:
        with archive.articles.open_media(ulid, ref) as stream:
            return parse(stream.read(), ref.content_hash)
    except NotFound:
        return None
    except Exception:  # a failed read, or untrusted bytes the reader did not expect
        logger.warning("no text of %s", ref.content_hash, exc_info=True)
        return None


def record(ulid: ULID, content_hash: str, parsed: Parsed) -> None:
    """Store ``parsed`` as the text of ``content_hash``: the pages of ``Pages``, the page-0 marker
    for ``Unreadable``. A ``HashMismatch`` stores nothing and is logged as an alarm naming the file
    and Article ``ulid``."""
    match parsed:
        case Pages(texts):
            indexer.store_media_text(content_hash, texts)
        case Unreadable():
            indexer.store_media_text(content_hash, ())
        case HashMismatch():
            logger.warning("media %s of %s does not match its hash", content_hash, ulid)
        case _:
            assert_never(parsed)


def fill(archive: Archive, ulid: ULID) -> dict[str, Parsed]:
    """``read`` and ``record`` each ``readable`` file of Article ``ulid``'s current media that has
    no text yet; returns the outcome per content hash of each file read (a failed read is absent).
    ``{}`` when the Article is gone. Never raises for a file's bytes."""
    try:
        files = readable(archive.articles.load(ulid).article.media)
    except NotFound:
        return {}
    done = indexer.hashes_with_text(r.content_hash for r in files)
    return {
        ref.content_hash: parsed
        for ref in files
        if ref.content_hash not in done and (parsed := _fill_one(archive, ulid, ref)) is not None
    }


def _fill_one(archive: Archive, ulid: ULID, ref: MediaRef) -> Parsed | None:
    """``read`` one file and ``record`` its outcome at once, so a later file that kills the job
    leaves this one stored."""
    parsed = read(archive, ulid, ref)
    if parsed is not None:
        record(ulid, ref.content_hash, parsed)
    return parsed


def missing(archive: Archive) -> tuple[ULID, ...]:
    """The Articles whose README decodes with a ``readable`` file that has no text yet."""
    files = {a.ulid: readable(a.media) for a in archive.articles.scan().readable}
    done = indexer.hashes_with_text(r.content_hash for refs in files.values() for r in refs)
    return tuple(
        ulid for ulid, refs in files.items() if any(r.content_hash not in done for r in refs)
    )
