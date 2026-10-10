"""The PDF text reader: one string per page in page order, a page cap, and no exception for a PDF
that cannot be read."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from tests._pdfs import text_pdf

from bundesarchiv.app.pdf import page_texts

#: A one-page PDF with an AES-256 user password (``qpdf --encrypt geheim geheim 256``).
_ENCRYPTED = (Path(__file__).parent / "encrypted.pdf").read_bytes()


def _jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (60, 80), (90, 90, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def test_each_page_gives_its_text_in_page_order_with_line_end_hyphens_joined() -> None:
    pdf = text_pdf(["Die Fahr-\nten im Lager", "", "Übung (Wald)"], first_page_image=_jpeg())

    assert page_texts(pdf, max_pages=10) == (
        "",
        "Die Fahrten im Lager",
        "",
        "Übung (Wald)",
    )


def test_pages_past_the_cap_are_not_read() -> None:
    assert page_texts(text_pdf(["eins", "zwei", "drei"]), max_pages=2) == ("eins", "zwei")


def test_a_page_that_cannot_be_loaded_gives_no_text_and_keeps_the_others() -> None:
    pdf = text_pdf(["eins", "zwei", "drei"]).replace(b"7 0 obj", b"77 0 obj")  # page 2 dangles

    assert page_texts(pdf, max_pages=10) == ("eins", "", "drei")


@pytest.mark.parametrize(
    "data",
    [b"", b"%PDF-1.4\n", text_pdf(["eins", "zwei"])[:200], _ENCRYPTED, text_pdf([])],
    ids=["empty", "header-only", "truncated", "encrypted", "no-pages"],
)
def test_a_pdf_that_cannot_be_read_gives_none_and_does_not_raise(data: bytes) -> None:
    assert page_texts(data, max_pages=10) is None
