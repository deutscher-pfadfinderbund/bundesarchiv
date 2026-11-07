"""A file's MIME type and its kind, decided from its ``MediaRef`` alone."""

import mimetypes

import pytest

from bundesarchiv.domain.files import FileKind, file_kind, mime_type
from bundesarchiv.domain.models import MediaRef


@pytest.mark.parametrize(
    ("filename", "recorded", "expected"),
    [("scan.pdf", "image/JPEG", "image/jpeg"), ("e.mp3", "", "audio/mpeg")],
)
def test_the_recorded_type_wins_else_the_extension_says(
    filename: str, recorded: str | None, expected: str
) -> None:
    assert mime_type(MediaRef(filename, "h", media_type=recorded)) == expected


def test_a_kind_needs_the_exact_major_type() -> None:
    assert file_kind(MediaRef("f", "h", media_type="imagery/x")) is FileKind.OTHER


def test_an_extension_means_what_the_stdlib_built_in_table_says() -> None:
    """A guessed type is the stdlib's, or none; every extension the stdlib types gets its kind."""
    stdlib = mimetypes.MimeTypes().types_map[True]
    wrong = {
        ext: (mime_type(ref), file_kind(ref))
        for ext, mime in stdlib.items()
        if mime_type(ref := MediaRef("f" + ext, "h")) not in {"", mime}
        or file_kind(ref) is not file_kind(MediaRef("f", "h", media_type=mime))
    }
    assert wrong == {}
