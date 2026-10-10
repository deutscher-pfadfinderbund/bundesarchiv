"""PDFs with a text layer, written by hand so a test controls every page's text."""

from collections.abc import Sequence
from io import BytesIO

from PIL import Image

_WIDTH, _HEIGHT = 595, 842  # A4 in points


def _escaped(line: str) -> bytes:
    raw = line.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_stream(text: str) -> bytes:
    """Each line of ``text`` on its own line of the page; ``""`` is a page without text."""
    if not text:
        return b""
    lines = b" T* ".join(b"(%s) Tj" % _escaped(line) for line in text.split("\n"))
    return b"BT /F1 11 Tf 14 TL 56 780 Td %s ET" % lines


def text_pdf(pages: Sequence[str], *, first_page_image: bytes | None = None) -> bytes:
    """A PDF with one page per string of ``pages``, each string that page's text layer (lines split
    on ``\\n``, Helvetica in WinAnsi, so any cp1252 text). ``first_page_image`` (JPEG bytes) becomes
    an image-only page 1 before the text pages."""
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    objects: list[bytes] = [b"", b"", font]  # catalog and page tree filled in last
    kids: list[int] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def add_page(content: bytes, resources: bytes) -> None:
        stream = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        kids.append(
            add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources %s /Contents %d 0 R >>"
                % (_WIDTH, _HEIGHT, resources, stream)
            )
        )

    if first_page_image is not None:
        with Image.open(BytesIO(first_page_image)) as image:
            width, height = image.size
        picture = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB"
            b" /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n%s\nendstream"
            % (width, height, len(first_page_image), first_page_image)
        )
        add_page(
            b"q %d 0 0 %d 0 0 cm /Im1 Do Q" % (_WIDTH, _HEIGHT),
            b"<< /XObject << /Im1 %d 0 R >> >>" % picture,
        )
    for text in pages:
        add_page(_text_stream(text), b"<< /Font << /F1 3 0 R >> >>")

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % kid for kid in kids),
        len(kids),
    )
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    trailer = b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
    return out + trailer % (len(objects) + 1, xref)
