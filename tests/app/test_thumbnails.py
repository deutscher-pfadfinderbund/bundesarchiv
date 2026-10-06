"""The thumbnail job's renderer seam: an image and a PDF's first page derive the same AVIF tile, only
an image derives the display version, and a PDF that cannot be read derives none without failing
the job."""

import threading
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, features
from tests._articles import make_article

from bundesarchiv.app import thumbnails
from bundesarchiv.app.thumbnails import Size, cached, generate_thumbnail, thumbnail_path
from bundesarchiv.domain.models import MediaRef
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


def _png(size: tuple[int, int] = (1200, 900)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (200, 60, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _rotated_jpeg() -> bytes:
    """A landscape JPEG whose EXIF orientation (6) tells a viewer to show it portrait."""
    buf = BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (800, 600), (90, 90, 90)).save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _broken_exif_jpeg() -> bytes:
    """A greyscale JPEG whose EXIF block has a broken TIFF header: Pillow raises SyntaxError
    reading it once the picture is converted to RGB."""
    buf = BytesIO()
    Image.new("L", (64, 48)).save(buf, format="JPEG", exif=b"Exif\x00\x00MM *\x00\x00\x00\x08")
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


def _stored(root: Path, filename: str, data: bytes, media_type: str) -> MediaRef:
    """Store ``data`` as a file of the Article; the canonical root sits under ``root``."""
    articles = ArticleRepository(LocalFsObjectStore(root / "canonical"))
    return articles.add_media(_ULID, filename, BytesIO(data), media_type=media_type)


def _cached(root: Path, ref: MediaRef) -> Path | None:
    articles = ArticleRepository(LocalFsObjectStore(root / "canonical"))
    return cached(articles, _ULID, ref, root / "thumbs", Size.DISPLAY)


def _display(root: Path, filename: str, data: bytes, media_type: str) -> Path | None:
    """Store ``data`` as the one file of an Article; its display version, derived on the miss."""
    return _cached(root, _stored(root, filename, data, media_type))


def _planted(root: Path, ref: MediaRef, data: bytes) -> Path:
    """A display version already in the cache for ``ref``'s bytes, holding ``data``."""
    path = thumbnail_path(root / "thumbs", ref.content_hash, Size.DISPLAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_pillow_encodes_avif() -> None:
    assert features.check("avif")


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
        assert thumbnail.format == "AVIF"
        assert max(thumbnail.size) == 480


def test_an_image_derives_its_display_version_on_the_first_miss(tmp_path: Path) -> None:
    path = _display(tmp_path, "scan.png", _png((2400, 1800)), "image/png")
    assert path is not None
    with Image.open(path) as display:
        assert (display.format, display.size) == ("AVIF", (1600, 1200))
    assert path.stat().st_mode & 0o777 == 0o644
    assert list(path.parent.iterdir()) == [path], "a temp file was left behind"


def test_an_empty_cache_file_is_derived_again(tmp_path: Path) -> None:
    ref = _stored(tmp_path, "scan.png", _png(), "image/png")
    path = _planted(tmp_path, ref, b"")
    assert _cached(tmp_path, ref) == path
    with Image.open(path) as display:
        assert display.format == "AVIF"


def test_the_kind_is_asked_before_the_cache(tmp_path: Path) -> None:
    """The same bytes stored as an image elsewhere left a display version; as a PDF they have none."""
    ref = _stored(tmp_path, "brief.pdf", _png(), "application/pdf")
    _planted(tmp_path, ref, b"display of the same bytes as an image")
    assert _cached(tmp_path, ref) is None


class _Turnstile:
    """The derive lock, telling the test when a request has started to wait on it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self) -> None:
        self.waiting.set()
        self.lock.acquire()

    def __exit__(self, *_: object) -> None:
        self.lock.release()


def test_a_request_that_waited_on_the_lock_takes_its_peers_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A race test would be flaky; the lock's re-check is pinned instead. The peer's version lands
    while this request waits on the lock, and the request serves it instead of deriving again."""
    ref = _stored(tmp_path, "scan.png", _png(), "image/png")
    turnstile = _Turnstile()
    monkeypatch.setattr(thumbnails, "_derive_lock", turnstile)
    served: list[Path | None] = []
    with turnstile.lock:
        request = threading.Thread(target=lambda: served.append(_cached(tmp_path, ref)))
        request.start()
        assert turnstile.waiting.wait(timeout=10)
        peers = _planted(tmp_path, ref, b"the peer's version")
    request.join(timeout=10)
    assert served == [peers]
    assert peers.read_bytes() == b"the peer's version"


def test_an_image_over_the_pixel_cap_derives_no_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(thumbnails, "_MAX_PIXELS", 1200 * 900 - 1)
    assert _display(tmp_path, "scan.png", _png((1200, 900)), "image/png") is None


def test_a_pdf_derives_no_display_version(tmp_path: Path) -> None:
    assert _display(tmp_path, "brief.pdf", _pdf(), "application/pdf") is None
    assert not (tmp_path / "thumbs").exists()


def test_a_photo_is_turned_the_way_its_exif_says(tmp_path: Path) -> None:
    path = _derive(tmp_path, "foto.jpg", _rotated_jpeg(), "image/jpeg")
    assert path is not None
    with Image.open(path) as thumbnail:
        assert thumbnail.size == (360, 480)


def test_a_page_box_however_large_renders_at_the_target_size(tmp_path: Path) -> None:
    """A page box of 7.2 million points a side still renders 480 px, never its claimed size."""
    path = _derive(tmp_path, "plan.pdf", _pdf((100, 100), resolution=0.001), "application/pdf")
    assert path is not None
    with Image.open(path) as thumbnail:
        assert thumbnail.size == (480, 480)


def test_a_photo_with_broken_exif_derives_no_thumbnail_and_does_not_raise(tmp_path: Path) -> None:
    assert _derive(tmp_path, "foto.jpg", _broken_exif_jpeg(), "image/jpeg") is None


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4\n", _pdf()[:300], _ENCRYPTED, _zero_page_pdf()],
    ids=["broken", "truncated", "encrypted", "zero-pages"],
)
def test_an_unreadable_pdf_derives_no_thumbnail_and_does_not_raise(
    tmp_path: Path, data: bytes
) -> None:
    assert _derive(tmp_path, "akte.pdf", data, "application/pdf") is None
