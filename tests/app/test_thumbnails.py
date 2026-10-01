"""The thumbnail job's renderer seam: an image and a PDF's first page derive the same WebP, and a
PDF that cannot be read derives none without failing the job."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from tests._articles import make_article

from bundesarchiv.app.thumbnails import generate_thumbnail, thumbnail_path
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMPC"

#: A one-page PDF with an AES-256 user password (``qpdf --encrypt geheim geheim 256``).
_ENCRYPTED = (Path(__file__).parent / "encrypted.pdf").read_bytes()


def _pdf(size: tuple[int, int] = (600, 800), resolution: float = 72.0) -> bytes:
    """A one-page PDF; its page box is ``size`` at ``resolution`` dpi."""
    buf = BytesIO()
    Image.new("RGB", size, (240, 240, 230)).save(buf, format="PDF", resolution=resolution)
    return buf.getvalue()


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (1200, 900), (200, 60, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _zero_page_pdf() -> bytes:
    """A well-formed PDF whose page tree holds no page."""
    objects = (b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [] /Count 0 >>")
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 3\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref


def _derive(root: Path, filename: str, data: bytes, media_type: str) -> Path | None:
    """Store ``data`` as the one file of an Article, run the job; the thumbnail it wrote, if any."""
    store = LocalFsObjectStore(root / "canonical")
    articles = ArticleRepository(store)
    ref = articles.add_media(_ULID, filename, BytesIO(data), media_type=media_type)
    articles.save(make_article(_ULID, collection_id="ROOT", media=(ref,)), 0, changed_by="tester")
    written = generate_thumbnail(store, _ULID, ref.content_hash, root / "thumbs")
    path = thumbnail_path(root / "thumbs", ref.content_hash)
    assert written == path.is_file()
    return path if written else None


@pytest.mark.parametrize(
    ("filename", "data", "media_type"),
    [("scan.png", _png(), "image/png"), ("brief.pdf", _pdf(), "application/pdf")],
    ids=["image", "pdf"],
)
def test_an_image_and_a_pdf_derive_through_the_same_seam(
    tmp_path: Path, filename: str, data: bytes, media_type: str
) -> None:
    path = _derive(tmp_path, filename, data, media_type)
    assert path is not None
    with Image.open(path) as thumbnail:
        assert thumbnail.format == "WEBP"
        assert max(thumbnail.size) == 480


def test_a_page_box_however_large_renders_at_the_target_size(tmp_path: Path) -> None:
    """A page box of 7.2 million points a side still renders 480 px, never its claimed size."""
    path = _derive(tmp_path, "plan.pdf", _pdf((100, 100), resolution=0.001), "application/pdf")
    assert path is not None
    with Image.open(path) as thumbnail:
        assert thumbnail.size == (480, 480)


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4\n", _pdf()[:300], _ENCRYPTED, _zero_page_pdf()],
    ids=["broken", "truncated", "encrypted", "zero-pages"],
)
def test_an_unreadable_pdf_derives_no_thumbnail_and_does_not_raise(
    tmp_path: Path, data: bytes
) -> None:
    assert _derive(tmp_path, "akte.pdf", data, "application/pdf") is None
