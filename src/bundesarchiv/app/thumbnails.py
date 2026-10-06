"""Thumbnail generation (Part 4.3) — a LOCAL derived cache, keyed by content-hash.

A file has up to two derived versions (``Size``): the AVIF tile of an image or of a PDF's first
page, and the AVIF display version of an image. Both are a DERIVED CACHE, not archive truth: keyed
purely by the file's content-hash and size (``thumbnail_path``), regenerable from canonical at any
time, NOT stored in the ObjectStore, NOT canonical, NOT mirrored, NOT backed up, and freely
prunable (README runbook). Identical bytes always yield the identical version, so the cache key is
the content-hash alone, whichever Article or file name the bytes sit under.

The worker makes the tile on upload (``generate_thumbnail``); a request makes whatever is missing
(``cached``). Every write lands by rename, so a concurrent reader never sees a torn file. A file's
bytes are untrusted: no content problem raises past ``_derive``, it only yields no version.

Reference semantics (ADR 0014): the worker job carries the Article's ulid and the content-hash and
re-derives at execution, reading the file through that Article's media entry (ADR 0019). A file's
kind picks its ``Renderer`` (``_RENDERERS``): images through Pillow (JPEG/PNG/TIFF — evaluated
against Pillow 12.x), PDFs through ``pdf_preview``. Any other kind (text, video, …) is a no-op.
"""

import io
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps

from bundesarchiv.app import pdf_preview
from bundesarchiv.domain.models import MediaRef, Ulid
from bundesarchiv.index.indexer import file_kind
from bundesarchiv.index.query import FileKind
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

logger = logging.getLogger(__name__)


class Size(IntEnum):
    """A derived version by its longest side (px). Pillow's ``thumbnail`` preserves aspect ratio
    and never upscales, so a small original is left at its own size."""

    TILE = 480
    DISPLAY = 1600


#: Chosen by eye on legacy PDF text pages and photos against WebP 80 (Wave MEDIA, 2026-10-06).
_AVIF_QUALITY = 60

#: The largest image (in pixels, as its header claims) a version is made of: the web process
#: decodes it in a request. The legacy corpus' largest is a 58.7 MP JPEG (7324 x 8014,
#: 2026-10-06); the cap sits below Pillow's own bomb warning (``MAX_IMAGE_PIXELS``, 89.5 MP).
_MAX_PIXELS = 80_000_000

#: A file's bytes and the longest side wanted in, an RGB picture of the file out (no smaller than
#: wanted unless the file itself is), or None when the file yields none. May raise for the file's
#: content; ``_derive`` turns that into no version.
Renderer = Callable[[BinaryIO, int], Image.Image | None]

# ponytail: one global derive lock; per-key locks if concurrent first views ever queue
_derive_lock = threading.Lock()


def _picture(source: BinaryIO, longest_side: int) -> Image.Image | None:
    """The image ``source`` holds, at most ``longest_side`` px, turned as its EXIF orientation says
    (as a browser shows the original). RGB because the preview only needs to look right (a paletted
    mode or stray alpha is dropped); the canonical file is untouched. An image over
    ``_MAX_PIXELS`` is None. Downscaled before it is turned, so only one full-size copy is held."""
    box = (longest_side, longest_side)
    with Image.open(source) as image:
        if image.width * image.height > _MAX_PIXELS:
            return None
        image.draft("RGB", box)  # a JPEG decodes at a reduced scale, still no smaller than box
        picture = image if image.mode == "RGB" else image.convert("RGB")
        picture.thumbnail(box)
        return ImageOps.exif_transpose(picture)


#: The one place a file kind picks its renderer; a kind without one gets no thumbnail.
_RENDERERS: dict[FileKind, Renderer] = {
    FileKind.IMAGE: _picture,
    FileKind.PDF: pdf_preview.first_page,
}

#: A PDF opens in a new tab, so only an image has a display version.
_KINDS: dict[Size, frozenset[FileKind]] = {
    Size.TILE: frozenset(_RENDERERS),
    Size.DISPLAY: frozenset({FileKind.IMAGE}),
}


def renders(ref: MediaRef, size: Size = Size.TILE) -> bool:
    """Whether ``ref``'s kind has a version of ``size``, so a job or request for it can make one."""
    return file_kind(ref) in _KINDS[size]


def thumbnail_path(thumbnail_root: Path, content_hash: str, size: Size = Size.TILE) -> Path:
    """The cache file for one blob's version of ``size``: written here, served by the web layer."""
    name = content_hash if size is Size.TILE else f"{content_hash}-{size.value}"
    return thumbnail_root / f"{name}.avif"


def is_cached(thumbnail_root: Path, content_hash: str, size: Size = Size.TILE) -> bool:
    """Whether the cache holds a version of ``size`` for the blob; an empty file is none."""
    try:
        return thumbnail_path(thumbnail_root, content_hash, size).stat().st_size > 0
    except OSError:
        return False


def generate_thumbnail(
    store: ObjectStore, ulid: Ulid, content_hash: str, thumbnail_root: Path
) -> bool:
    """Derive the tile for the media file with ``content_hash`` on Article ``ulid`` into its
    ``thumbnail_path`` under ``thumbnail_root``. Returns True if a tile was written, False if it was
    a no-op (no such Article, no such file on it, a kind without a renderer, or a file its renderer
    cannot read: corrupt, encrypted, empty).

    Idempotent (overwrites with identical bytes); re-derives from canonical every time (reference
    semantics). Never raises for the file's content, so a mixed-media Article never fails the job."""
    articles = ArticleRepository(store)
    try:
        media = articles.load(ulid).article.media
    except NotFound:
        return False  # the Article is gone from canonical → nothing to derive
    ref = next((entry for entry in media if entry.content_hash == content_hash), None)
    if ref is None:
        return False  # the file left the Article before the job ran
    return _derive(articles, ulid, ref, thumbnail_root, Size.TILE)


def cached(
    articles: ArticleRepository, ulid: Ulid, ref: MediaRef, thumbnail_root: Path, size: Size
) -> Path | None:
    """The cache file of ``ref``'s version of ``size``, derived first on a miss; None when the file
    yields none. ``ref`` is on Article ``ulid`` — the caller already loaded and authorized it.
    The kind is asked first: the same bytes under another kind may have a cached version."""
    if not renders(ref, size):
        return None
    path = thumbnail_path(thumbnail_root, ref.content_hash, size)
    if is_cached(thumbnail_root, ref.content_hash, size):
        return path
    with _derive_lock:  # a request that waited here finds the version its peer just made
        if is_cached(thumbnail_root, ref.content_hash, size) or _derive(
            articles, ulid, ref, thumbnail_root, size
        ):
            return path
    return None


def _derive(
    articles: ArticleRepository, ulid: Ulid, ref: MediaRef, thumbnail_root: Path, size: Size
) -> bool:
    if not renders(ref, size):
        return False
    try:
        with articles.open_media(ulid, ref) as stream:
            avif = _avif(_RENDERERS[file_kind(ref)], stream, size)
    except NotFound:
        return False  # the file is gone from canonical → nothing to derive
    except Exception:  # untrusted bytes: any decoder or encoder failure means no version
        logger.warning("no %s version of %s", size.name, ref.content_hash, exc_info=True)
        return False
    if avif is None:
        return False
    _write_atomically(thumbnail_path(thumbnail_root, ref.content_hash, size), avif)
    return True


def _avif(render: Renderer, source: BinaryIO, size: Size) -> bytes | None:
    """What ``render`` makes of ``source``, downscaled to ``size``, as AVIF."""
    preview = render(source, size)
    if preview is None:
        return None
    preview.thumbnail((size, size))
    out = io.BytesIO()
    preview.save(out, format="AVIF", quality=_AVIF_QUALITY)
    return out.getvalue()


def _write_atomically(destination: Path, data: bytes) -> None:
    """The temp file is removed on any failure; after the rename there is nothing left to remove."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".tmp", delete_on_close=False
    ) as tmp:
        tmp.write(data)
        os.fchmod(tmp.fileno(), 0o644)
        tmp.close()
        Path(tmp.name).replace(destination)
