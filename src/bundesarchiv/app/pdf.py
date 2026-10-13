"""The PDF backend: the only module that knows it (PDFium, through ``pypdfium2``). Swapping the
backend (poppler, MuPDF, a service) replaces this module and nothing else."""

from contextlib import closing
from typing import BinaryIO

import pypdfium2 as pdfium  # noqa: TID251
from PIL import Image  # noqa: TID251

#: PDFium's mark for a hyphen it found at a line end; the word continues on the next line.
_LINE_END_HYPHEN = "\ufffe"


def first_page(source: BinaryIO, longest_side: int) -> Image.Image | None:
    """The first page of the PDF ``source`` holds, its longest side ``longest_side`` px however
    large the page box claims to be, or None when there is no page to show: broken, encrypted or
    empty. Never raises for the PDF's content."""
    try:
        with (
            pdfium.PdfDocument(source) as pdf,
            closing(pdf[0]) as page,
            closing(page.render(scale=longest_side / max(page.get_size()))) as bitmap,
        ):
            picture: Image.Image = bitmap.to_pil().convert("RGB")  # a copy: may share the buffer
            return picture
    except pdfium.PdfiumError, OSError, ValueError:
        return None


def page_texts(data: bytes, *, max_pages: int) -> tuple[str, ...] | None:
    """The text layer of each page of the PDF ``data``, page 1 first, at most ``max_pages`` pages
    (``""`` for a page without one), or None for one PDFium cannot open: broken, encrypted or
    without pages. Never raises for the PDF's content."""
    try:
        with pdfium.PdfDocument(data) as pdf:
            return tuple(_page_text(pdf, index) for index in range(min(len(pdf), max_pages)))
    except pdfium.PdfiumError, ValueError:
        return None


def _page_text(pdf: pdfium.PdfDocument, index: int) -> str:
    try:
        with closing(pdf[index]) as page, closing(page.get_textpage()) as textpage:
            text: str = textpage.get_text_range()
            return text.replace(_LINE_END_HYPHEN, "")
    except pdfium.PdfiumError:
        return ""
