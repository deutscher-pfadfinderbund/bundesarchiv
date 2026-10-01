"""A PDF's first page as a picture: the only module that knows the PDF backend (PDFium, through
``pypdfium2``). Swapping the backend (poppler, MuPDF, a service) replaces this module and nothing
else; ``thumbnails`` calls ``first_page`` and owns the rest."""

from contextlib import closing
from typing import BinaryIO

import pypdfium2 as pdfium
from PIL import Image


def first_page(source: BinaryIO, longest_side: int) -> Image.Image | None:
    """The first page of the PDF ``source`` holds, its longest side ``longest_side`` px however
    large the page box claims to be, or None when there is no page to show: broken, encrypted or
    empty. Never raises for the PDF's content; every PDFium handle is closed on return."""
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
