"""``manage.py move_readme_marker`` (ADR 0019, amended 2026-10-16): every current README in the old
shape gets its marker moved and nothing else, any other README is left as it is and named, and no
run writes a version or history."""

import io
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from tests._readmes import OLD_MARKER

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Article, Collection
from bundesarchiv.persistence._front_matter import HEAD
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS
from bundesarchiv.persistence._writer import history_key

OLD_HEAD = f"{OLD_MARKER}---\n".encode()
EDITED, CURRENT, BESTAND, CRLF = "01EDITED", "01CURRENT", "01BESTAND", "01CRLF"


@pytest.fixture
def archive(tmp_path: Path) -> Iterator[Archive]:
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        yield Archive.canonical()


def _tree(archive: Archive) -> dict[str, bytes]:
    return {key: archive.store.read(key) for key in archive.store.list()}


def test_only_the_readmes_in_the_old_shape_move_their_marker(archive: Archive) -> None:
    archive.collections.save(Collection(BESTAND, "Bund"), 0, changed_by="tester")
    article = Article(EDITED, "Brief", BESTAND, body="Text\n\n---\n")
    archive.articles.save(article, 0, changed_by="tester")
    archive.articles.save(replace(article, title="Brief an Jürgen"), 1, changed_by="tester")
    for ulid in (CURRENT, CRLF):
        archive.articles.save(Article(ulid, "Foto", BESTAND), 0, changed_by="tester")
    old = [
        COLLECTIONS.readme_key(BESTAND),
        ARTICLES.readme_key(EDITED),
        history_key(ARTICLES.folder(EDITED), 1),
        ARTICLES.readme_key(CRLF),
    ]
    for key in old:
        archive.store.write_atomic(key, archive.store.read(key).replace(HEAD.encode(), OLD_HEAD, 1))
    crlf = archive.store.read(ARTICLES.readme_key(CRLF)).replace(b"\n", b"\r\n")
    archive.store.write_atomic(ARTICLES.readme_key(CRLF), crlf)
    before, loaded = _tree(archive), archive.articles.load(EDITED)

    out = io.StringIO()
    with pytest.raises(CommandError, match=r"^Skipped: 1$"):
        call_command("move_readme_marker", stdout=out)

    assert out.getvalue() == (
        "Rewritten: 2\n"
        "Already new: 1\n"
        f"Not the old shape, left as it is: {ARTICLES.readme_key(CRLF)}\n"
    )
    moved = old[:2]
    assert _tree(archive) == {
        **before,
        **{key: before[key].replace(OLD_HEAD, HEAD.encode(), 1) for key in moved},
    }
    assert archive.articles.load(EDITED) == loaded

    out = io.StringIO()
    with pytest.raises(CommandError):
        call_command("move_readme_marker", stdout=out)
    assert out.getvalue().startswith("Rewritten: 0\nAlready new: 3\n")
