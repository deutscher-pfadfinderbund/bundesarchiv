"""Thumbnail generation (Part 4.3) — a LOCAL derived cache, keyed by content-hash.

A thumbnail is a downscaled WebP preview of an image file or of a PDF's first page. It is a DERIVED
CACHE, not archive truth: keyed purely by the file's content-hash (``thumbnail_path``), regenerable
from canonical at any time, NOT stored in the ObjectStore, NOT canonical, NOT mirrored, NOT backed
up, and freely prunable (README runbook). Identical bytes always yield the identical thumbnail, so
the cache key is the content-hash alone, whichever Article or file name the bytes sit under.

Reference semantics (ADR 0014): the worker job carries the Article's ulid and the content-hash and
re-derives at execution, reading the file through that Article's media entry (ADR 0019). A file's
kind picks its ``Renderer`` (``_RENDERERS``): images through Pillow (JPEG/PNG/TIFF — evaluated
against Pillow 12.x), PDFs through ``pdf_preview``. Any other kind (text, video, …) is a no-op.

Idempotent: re-running overwrites the same file with identical bytes.
"""

import io
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from bundesarchiv.app import pdf_preview
from bundesarchiv.domain.models import MediaRef, Ulid
from bundesarchiv.index.indexer import file_kind
from bundesarchiv.index.query import FileKind
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: Longest-side target for the thumbnail (px). Pillow's ``thumbnail`` preserves aspect ratio and
#: never upscales, so a small original is left at its own size.
_LONGEST_SIDE = 480

#: A file's bytes and the longest side wanted in, an RGB picture of the file out (no smaller than
#: wanted unless the file itself is), or None when the file yields none. Never raises for the
#: file's content: a broken file is None.
Renderer = Callable[[BinaryIO, int], Image.Image | None]


def _picture(source: BinaryIO, longest_side: int) -> Image.Image | None:
    """The image ``source`` holds, decoded by Pillow; ``longest_side`` is left to the downscale.
    RGB because the preview only needs to look right (a paletted mode or stray alpha is dropped);
    the canonical file is untouched. An image Pillow refuses as a decompression bomb is None too."""
    try:
        with Image.open(source) as image:
            image.load()
            return image.convert("RGB")
    except UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError:
        return None


#: The one place a file kind picks its renderer; a kind without one gets no thumbnail.
_RENDERERS: dict[FileKind, Renderer] = {
    FileKind.IMAGE: _picture,
    FileKind.PDF: pdf_preview.first_page,
}


def renders(ref: MediaRef) -> bool:
    """Whether ``ref``'s kind has a renderer, so a thumbnail job for it can produce one."""
    return file_kind(ref) in _RENDERERS


def thumbnail_path(thumbnail_root: Path, content_hash: str) -> Path:
    """The cache file for one blob's thumbnail: the job writes it, the web layer serves it."""
    return thumbnail_root / f"{content_hash}.webp"


def generate_thumbnail(
    store: ObjectStore, ulid: Ulid, content_hash: str, thumbnail_root: Path
) -> bool:
    """Derive a longest-side ~480px WebP thumbnail for the media file with ``content_hash`` on
    Article ``ulid`` and write it to its ``thumbnail_path`` under ``thumbnail_root``. Returns True
    if a thumbnail was written, False if it was a no-op (no such Article, no such file on it, a kind
    without a renderer, or a file its renderer cannot read: corrupt, encrypted, empty).

    Idempotent (overwrites with identical bytes); re-derives from canonical every time (reference
    semantics). Never raises for the file's content, so a mixed-media Article never fails the job."""
    articles = ArticleRepository(store)
    try:
        media = articles.load(ulid).article.media
        ref = next((entry for entry in media if entry.content_hash == content_hash), None)
        if ref is None:
            return False  # the file left the Article before the job ran
        render = _RENDERERS.get(file_kind(ref))
        if render is None:
            return False
        with articles.open_media(ulid, ref) as stream:
            webp = _webp(render, stream)
    except NotFound:
        return False  # the Article or its file is gone from canonical → nothing to derive
    if webp is None:
        return False
    destination = thumbnail_path(thumbnail_root, content_hash)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(webp)
    return True


def _webp(render: Renderer, source: BinaryIO) -> bytes | None:
    """What ``render`` makes of ``source``, downscaled to the longest-side target, as WebP."""
    preview = render(source, _LONGEST_SIDE)
    if preview is None:
        return None
    preview.thumbnail((_LONGEST_SIDE, _LONGEST_SIDE))
    out = io.BytesIO()
    preview.save(out, format="WEBP")
    return out.getvalue()
