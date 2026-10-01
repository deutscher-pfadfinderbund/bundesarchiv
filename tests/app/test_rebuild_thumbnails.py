"""``manage.py rebuild_thumbnails``: every missing thumbnail derived from the canonical tree."""

import re
from io import BytesIO, StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import override_settings
from PIL import Image
from tests._articles import make_article

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import thumbnail_path

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMPB"


def _png(color: tuple[int, int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (600, 400), color).save(buf, format="PNG")
    return buf.getvalue()


def _generated(out: StringIO) -> list[str]:
    return re.findall(r"\d+", out.getvalue())


def test_it_derives_the_missing_skips_the_present_and_a_second_run_derives_nothing(
    tmp_path: Path,
) -> None:
    thumbs = tmp_path / "thumbs"
    with override_settings(
        BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical"),
        BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs),
    ):
        articles = Archive.canonical().articles
        present = articles.add_media(_ULID, "a.png", BytesIO(_png((200, 60, 40))), "image/png")
        missing = articles.add_media(_ULID, "b.png", BytesIO(_png((40, 120, 200))), "image/png")
        pdf = articles.add_media(_ULID, "p.pdf", BytesIO(b"%PDF-1.4\n"), "application/pdf")
        articles.save(
            make_article(_ULID, collection_id="ROOT", media=(present, missing, pdf)),
            0,
            changed_by="tester",
        )
        kept = thumbnail_path(thumbs, present.content_hash)
        kept.parent.mkdir()
        kept.write_bytes(b"already here")
        first, second = StringIO(), StringIO()
        call_command("rebuild_thumbnails", stdout=first)
        call_command("rebuild_thumbnails", stdout=second)

    assert kept.read_bytes() == b"already here"
    with Image.open(thumbnail_path(thumbs, missing.content_hash)) as derived:
        assert derived.format == "WEBP"
    assert not thumbnail_path(thumbs, pdf.content_hash).exists()
    assert (_generated(first), _generated(second)) == (["1"], ["0"])
