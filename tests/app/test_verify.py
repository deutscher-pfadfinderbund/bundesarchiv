"""``manage.py verify``, the fixity check (ADR 0019 "Fixity"): it names what is wrong with the
canonical tree, changes nothing, and fails when it found anything."""

import io
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Article, Collection, MediaRef
from bundesarchiv.persistence._writer import history_key, readme_key

ARTICLE, BESTAND = "01ARTIKEL", "01BESTAND"


@pytest.fixture
def archive(tmp_path: Path) -> Iterator[Archive]:
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        yield Archive.canonical()


@pytest.fixture
def scans(archive: Archive) -> tuple[MediaRef, MediaRef]:
    """A Bestand saved twice, and an Article saved twice: its first version names a scan and a
    second file uploaded under the same name, its second version only the scan."""
    archive.collections.save(Collection(BESTAND, "Bund"), 0, changed_by="tester")
    archive.collections.save(Collection(BESTAND, "Bund (alt)"), 1, changed_by="tester")
    scan = archive.articles.add_media(ARTICLE, "Scan.pdf", io.BytesIO(b"%PDF eins"))
    twin = archive.articles.add_media(ARTICLE, "Scan.pdf", io.BytesIO(b"%PDF zwei"))
    article = Article(ARTICLE, "Brief", BESTAND, media=(scan, twin))
    archive.articles.save(article, 0, changed_by="tester")
    archive.articles.save(replace(article, media=(scan,)), 1, changed_by="tester")
    return scan, twin


def _findings(count: int = 1) -> str:
    out = io.StringIO()
    with pytest.raises(CommandError, match=rf"^Befunde: {count}$"):
        call_command("verify", stdout=out)
    return out.getvalue()


def test_a_clean_tree_reports_clean(scans: tuple[MediaRef, MediaRef]) -> None:
    """Clean, although the second file is stored under another name than its own and only the
    Article's older version names it."""
    assert scans[1].stored_name is not None
    out = io.StringIO()
    call_command("verify", stdout=out)
    assert out.getvalue() == (
        "Geprüft: 4 README-Versionen, 2 Mediendateien\n"
        "Unlesbare README-Versionen: 0\n"
        "Unlesbare Dateien: 0\n"
        "Mediendateien mit abweichender Prüfsumme: 0\n"
        "Verweise ohne Datei: 0\n"
        "Dateien ohne Verweis: 0\n"
        "Keine Befunde.\n"
    )


@pytest.mark.parametrize("which", [0, 1], ids=["named-now", "named-before"])
def test_a_flipped_byte_is_found(
    archive: Archive, scans: tuple[MediaRef, MediaRef], which: int
) -> None:
    key = archive.articles.media_key(ARTICLE, scans[which])
    data = archive.store.read(key)
    archive.store.write_atomic(key, bytes([data[0] ^ 1]) + data[1:])
    assert f"Mediendateien mit abweichender Prüfsumme: 1\n  {key}\n" in _findings()


@pytest.mark.parametrize("which", [0, 1], ids=["named-now", "named-before"])
def test_a_missing_file_is_found(
    archive: Archive, scans: tuple[MediaRef, MediaRef], which: int
) -> None:
    key = archive.articles.media_key(ARTICLE, scans[which])
    archive.store.delete(key)
    assert f"Verweise ohne Datei: 1\n  {key}\n" in _findings()


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(f"articles/{ARTICLE}/media/Fremd.pdf", id="beside-named-files"),
        pytest.param(f"articles/{ARTICLE}/changes/2.json", id="older-layout"),
        pytest.param("articles/01WAISE/media/Scan.pdf", id="folder-without-readme"),
        pytest.param("notiz.txt", id="outside-every-record"),
    ],
)
def test_an_unreferenced_file_is_found_and_left_alone(
    archive: Archive, scans: tuple[MediaRef, MediaRef], key: str
) -> None:
    archive.store.write_atomic(key, b"Notiz")
    before = list(archive.store.list_entries())
    assert f"Dateien ohne Verweis: 1\n  {key}\n" in _findings()
    assert list(archive.store.list_entries()) == before


@pytest.mark.parametrize(
    ("key", "data"),
    [
        pytest.param(readme_key(f"articles/{ARTICLE}"), b"kein README", id="article"),
        pytest.param(readme_key(f"articles/{ARTICLE}"), b"\xff\xfe", id="article-not-utf8"),
        pytest.param(history_key(f"collections/{BESTAND}", 1), b"kein README", id="history"),
    ],
)
def test_an_unreadable_readme_version_is_found(
    archive: Archive, scans: tuple[MediaRef, MediaRef], key: str, data: bytes
) -> None:
    archive.store.write_atomic(key, data)
    assert f"Unlesbare README-Versionen: 1\n  {key}\n" in _findings()


def test_an_unreadable_file_is_found_and_the_check_goes_on(
    tmp_path: Path, archive: Archive, scans: tuple[MediaRef, MediaRef]
) -> None:
    key = archive.articles.media_key(ARTICLE, scans[0])
    stranger = archive.articles.media_key(ARTICLE, MediaRef("Fremd.pdf", "0" * 64))
    archive.store.write_atomic(stranger, b"Notiz")
    locked = (tmp_path / "canonical").joinpath(*key.split("/"))
    locked.chmod(0o000)
    try:
        out = _findings(2)
    finally:
        locked.chmod(0o600)  # so tmp_path cleanup can remove it
    assert f"Unlesbare Dateien: 1\n  {key}\n" in out
    assert f"Dateien ohne Verweis: 1\n  {stranger}\n" in out
