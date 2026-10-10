"""The page text of media files, read once per file into ``MediaText`` (ADR 0023).

v1 reads the text layer of PDFs (``pdf.page_texts``). A hash with rows counts as done; a file that
gave nothing usable stores the page-0 marker, so it counts as done too. Only a failed read or bytes
that do not match their hash leave no rows, and the next fill tries again. A file's bytes are
untrusted: no content problem raises past ``extract``.

``unread`` and ``parse`` decide; ``extract`` and ``missing`` read the archive and the rows.
"""

import io
import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from bundesarchiv.app import pdf
from bundesarchiv.domain.models import MediaRef, Ulid
from bundesarchiv.index import indexer
from bundesarchiv.index.query import FileKind
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository, content_digest

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


def unread(media: Iterable[MediaRef], done: Collection[str]) -> tuple[MediaRef, ...]:
    """The files of ``media`` that ``reads`` and whose hash is not in ``done``, one per hash."""
    return tuple(
        {r.content_hash: r for r in media if reads(r) and r.content_hash not in done}.values()
    )


def parse(data: bytes, content_hash: str) -> Parsed:
    """What the file ``data``, claimed to have ``content_hash``, gives (text is found by hash)."""
    if content_digest(io.BytesIO(data))[0] != content_hash:
        return HashMismatch()
    texts = pdf.page_texts(data, max_pages=MAX_PAGES)
    return Pages(texts) if texts else Unreadable()


def extract(store: ObjectStore, ulid: Ulid) -> int:
    """Store the text of each file of Article ``ulid``'s current media that is still ``unread``;
    returns how many files were stored. 0 when the Article is gone. Never raises for a file's
    bytes."""
    articles = ArticleRepository(store)
    try:
        media = articles.load(ulid).article.media
    except NotFound:
        return 0
    stored = 0
    for ref in unread(media, indexer.hashes_with_text(r.content_hash for r in media if reads(r))):
        try:
            with articles.open_media(ulid, ref) as stream:
                data = stream.read()  # held whole (largest legacy PDF 69 MB)
            parsed = parse(data, ref.content_hash)
        except NotFound:
            continue  # the file is gone from canonical
        except Exception:  # a failed read, or untrusted bytes the reader did not expect: retried
            logger.warning("no text of %s", ref.content_hash, exc_info=True)
            continue
        match parsed:
            case HashMismatch():
                logger.warning("media %s of %s does not match its hash", ref.content_hash, ulid)
            case Pages(texts):
                indexer.store_media_text(ref.content_hash, texts)
                stored += 1
            case Unreadable():
                indexer.store_media_text(ref.content_hash, ())
                stored += 1
    return stored


def missing(store: ObjectStore) -> tuple[Ulid, ...]:
    """The readable Articles with a file that is still ``unread``."""
    articles = ArticleRepository(store).scan().readable
    done = indexer.hashes_with_text(r.content_hash for a in articles for r in a.media if reads(r))
    return tuple(article.ulid for article in articles if unread(article.media, done))
