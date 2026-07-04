"""Thumbnail generation (Part 4.3) — a LOCAL derived cache, keyed by content-hash.

A thumbnail is a downscaled WebP preview of an image blob. It is a DERIVED CACHE, not archive
truth: keyed purely by the blob's content-hash (``THUMBNAIL_ROOT/<hash>.webp``), regenerable from
canonical at any time, NOT stored in the ObjectStore, NOT canonical, NOT mirrored, NOT backed up,
and freely prunable (README runbook). Because media is content-addressed and write-once, identical
bytes always yield the identical thumbnail — so the cache key is the content-hash alone, and the
job that produces it is a pure reference over that hash.

Reference semantics (ADR 0014): the worker job carries only the content-hash and re-derives from
the blob at execution — it locates ANY canonical blob with that hash (the same bytes may be attached
to several Articles; they all thumbnail to the same WebP). Non-image blobs (PDF, text, …) are a
no-op: only the corpus image types (JPEG/PNG/TIFF — evaluated against Pillow 12.x) thumbnail.

Idempotent: re-running overwrites the same ``<hash>.webp`` with identical bytes.
"""

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from bundesarchiv.persistence.objectstore import ObjectStore

#: Longest-side target for the thumbnail (px). Pillow's ``thumbnail`` preserves aspect ratio and
#: never upscales, so a small original is left at its own size.
_LONGEST_SIDE = 480

#: The store-relative media-key infix — a blob lives at ``articles/<ulid>/media/<content_hash>``.
_MEDIA_INFIX = "/media/"


def generate_thumbnail(store: ObjectStore, content_hash: str, thumbnail_root: Path) -> bool:
    """Derive a longest-side ~480px WebP thumbnail for the blob with ``content_hash`` and write it to
    ``thumbnail_root/<content_hash>.webp``. Returns True if a thumbnail was written, False if it was
    a no-op (no such blob, or the blob is not a decodable image — PDF/text/etc.).

    Idempotent (overwrites with identical bytes); re-derives from canonical every time (reference
    semantics). Never raises for a non-image blob — a corrupt or non-image blob is a silent no-op so
    a mixed-media Article never fails the job."""
    data = _find_blob(store, content_hash)
    if data is None:
        return False  # the blob is gone from canonical (deleted/never stored) → nothing to derive
    webp = _thumbnail_webp(data)
    if webp is None:
        return False  # not a decodable image (PDF, text, video, corrupt) → no-op, by design
    destination = thumbnail_root / f"{content_hash}.webp"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(webp)
    return True


def _find_blob(store: ObjectStore, content_hash: str) -> bytes | None:
    """The bytes of any canonical media blob whose key ends in ``/media/<content_hash>``, or None if
    none is stored. Content-addressed + write-once means every match holds identical bytes, so the
    first is representative — the thumbnail is Article-independent."""
    suffix = f"{_MEDIA_INFIX}{content_hash}"
    key = next((k for k in store.list("articles/") if k.endswith(suffix)), None)
    return None if key is None else store.read(key)


def _thumbnail_webp(data: bytes) -> bytes | None:
    """Downscale ``data`` to a longest-side ~480px WebP, or None if the bytes are not a decodable
    image. Converts to RGB (WebP has no place for a paletted/gray mode's oddities and a stray alpha
    profile is dropped) — the preview only needs to look right, not preserve archival fidelity (the
    canonical blob is untouched)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            preview = image.convert("RGB")
    except UnidentifiedImageError, OSError, ValueError:
        return None  # not an image Pillow can decode → caller treats as a no-op
    preview.thumbnail((_LONGEST_SIDE, _LONGEST_SIDE))
    out = io.BytesIO()
    preview.save(out, format="WEBP")
    return out.getvalue()
