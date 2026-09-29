"""Thumbnail generation (Part 4.3) — a LOCAL derived cache, keyed by content-hash.

A thumbnail is a downscaled WebP preview of an image file. It is a DERIVED CACHE, not archive
truth: keyed purely by the file's content-hash (``thumbnail_path``), regenerable from
canonical at any time, NOT stored in the ObjectStore, NOT canonical, NOT mirrored, NOT backed up,
and freely prunable (README runbook). Identical bytes always yield the identical thumbnail, so the
cache key is the content-hash alone, whichever Article or file name the bytes sit under.

Reference semantics (ADR 0014): the worker job carries the Article's ulid and the content-hash and
re-derives at execution, reading the file through that Article's media entry (ADR 0019). Non-image
files (PDF, text, …) are a no-op: only the corpus image types (JPEG/PNG/TIFF — evaluated against
Pillow 12.x) thumbnail.

Idempotent: re-running overwrites the same file with identical bytes.
"""

import io
from pathlib import Path
from typing import BinaryIO

from PIL import Image, UnidentifiedImageError

from bundesarchiv.domain.models import Ulid
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: Longest-side target for the thumbnail (px). Pillow's ``thumbnail`` preserves aspect ratio and
#: never upscales, so a small original is left at its own size.
_LONGEST_SIDE = 480


def thumbnail_path(thumbnail_root: Path, content_hash: str) -> Path:
    """The cache file for one blob's thumbnail: the job writes it, the web layer serves it."""
    return thumbnail_root / f"{content_hash}.webp"


def generate_thumbnail(
    store: ObjectStore, ulid: Ulid, content_hash: str, thumbnail_root: Path
) -> bool:
    """Derive a longest-side ~480px WebP thumbnail for the media file with ``content_hash`` on
    Article ``ulid`` and write it to its ``thumbnail_path`` under ``thumbnail_root``. Returns True
    if a thumbnail was written, False if it was a no-op (no such Article, no such file on it, or the
    file is not a decodable image — PDF/text/etc.).

    Idempotent (overwrites with identical bytes); re-derives from canonical every time (reference
    semantics). Never raises for a non-image file — a corrupt or non-image file is a silent no-op so
    a mixed-media Article never fails the job."""
    articles = ArticleRepository(store)
    try:
        media = articles.load(ulid).article.media
        ref = next((entry for entry in media if entry.content_hash == content_hash), None)
        if ref is None:
            return False  # the file left the Article before the job ran
        with articles.open_media(ulid, ref) as stream:
            webp = _thumbnail_webp(stream)
    except NotFound:
        return False  # the Article or its file is gone from canonical → nothing to derive
    if webp is None:
        return False  # not a decodable image (PDF, text, video, corrupt) → no-op, by design
    destination = thumbnail_path(thumbnail_root, content_hash)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(webp)
    return True


def _thumbnail_webp(source: BinaryIO) -> bytes | None:
    """Downscale the image ``source`` holds to a longest-side ~480px WebP, or None if the bytes are
    not a decodable image. Converts to RGB (WebP has no place for a paletted/gray mode's oddities and
    a stray alpha profile is dropped) — the preview only needs to look right, not preserve archival
    fidelity (the canonical file is untouched)."""
    try:
        with Image.open(source) as image:
            image.load()
            preview = image.convert("RGB")
    except UnidentifiedImageError, OSError, ValueError:
        return None  # not an image Pillow can decode → caller treats as a no-op
    preview.thumbnail((_LONGEST_SIDE, _LONGEST_SIDE))
    out = io.BytesIO()
    preview.save(out, format="WEBP")
    return out.getvalue()
