"""``manage.py rebuild_thumbnails``: every missing thumbnail derived from the canonical tree, and
one file that yields none never stops the run."""

import re
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import override_settings
from PIL import Image
from tests._articles import make_article

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import thumbnail_path

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMPB"


def _encoded(size: tuple[int, int], color: tuple[int, int, int], format: str) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format=format)
    return buf.getvalue()


def _generated(out: StringIO) -> list[str]:
    return re.findall(r"\d+", out.getvalue())


def test_it_derives_the_missing_skips_the_present_and_a_second_run_derives_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF is derived like an image; a picture Pillow refuses as a decompression bomb (more than
    twice ``MAX_IMAGE_PIXELS``) derives nothing and the run goes on past it."""
    thumbs = tmp_path / "thumbs"
    with override_settings(
        BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical"),
        BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs),
    ):
        articles = Archive.canonical().articles
        present = articles.add_media(
            _ULID, "a.png", BytesIO(_encoded((100, 100), (200, 60, 40), "PNG")), "image/png"
        )
        bomb = articles.add_media(
            _ULID, "b.png", BytesIO(_encoded((300, 300), (90, 90, 90), "PNG")), "image/png"
        )
        missing = articles.add_media(
            _ULID, "c.png", BytesIO(_encoded((100, 100), (40, 120, 200), "PNG")), "image/png"
        )
        pdf = articles.add_media(
            _ULID, "p.pdf", BytesIO(_encoded((60, 80), (240, 240, 230), "PDF")), "application/pdf"
        )
        articles.save(
            make_article(_ULID, collection_id="ROOT", media=(present, bomb, missing, pdf)),
            0,
            changed_by="tester",
        )
        kept = thumbnail_path(thumbs, present.content_hash)
        kept.parent.mkdir()
        kept.write_bytes(b"already here")
        first, second = StringIO(), StringIO()
        with monkeypatch.context() as bombs_refused:
            bombs_refused.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)
            call_command("rebuild_thumbnails", stdout=first)
            call_command("rebuild_thumbnails", stdout=second)

    assert kept.read_bytes() == b"already here"
    for derived in (missing, pdf):
        with Image.open(thumbnail_path(thumbs, derived.content_hash)) as thumbnail:
            assert thumbnail.format == "WEBP"
    assert not thumbnail_path(thumbs, bomb.content_hash).exists()
    assert (_generated(first), _generated(second)) == (["2"], ["0"])
