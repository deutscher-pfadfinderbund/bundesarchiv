"""``manage.py relayout_readmes`` (ADR 0019, amended 2026-10-16): every current README the writer
can reproduce gets the writer's bytes, any other is left as it is and named, and no run writes a
version or history."""

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from tests._readmes import OLD_ARTICLE, OLD_COLLECTION

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Article, Collection
from bundesarchiv.persistence._layout import ARTICLES, COLLECTIONS
from bundesarchiv.persistence._writer import history_key

BUND, CURRENT = "01BUND", "01CURRENT"
OLD, BROKEN, OLDEST = "01J0", "01BROKEN", "01OLDEST"
OLD_BESTAND, ODD = "01BESTAND", "01ODD"


@pytest.fixture
def archive(tmp_path: Path) -> Iterator[Archive]:
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        yield Archive.canonical()


def _tree(archive: Archive) -> dict[str, bytes]:
    return {key: archive.store.read(key) for key in archive.store.list()}


def test_only_the_readmes_the_writer_reproduces_are_rewritten(archive: Archive) -> None:
    archive.collections.save(Collection(BUND, "Bund"), 0, changed_by="tester")
    archive.articles.save(Article(CURRENT, "Foto", BUND), 0, changed_by="tester")
    old_files = {
        ARTICLES.readme_key(OLD): OLD_ARTICLE.encode(),
        history_key(ARTICLES.folder(OLD), 2): OLD_ARTICLE.replace(
            "version: 3", "version: 2"
        ).encode(),
        COLLECTIONS.readme_key(OLD_BESTAND): OLD_COLLECTION.encode(),
        COLLECTIONS.readme_key(ODD): f"{OLD_COLLECTION}Notiz\n".encode(),
        ARTICLES.readme_key(BROKEN): b"---\ntitle: [unclosed\n---\n",
        ARTICLES.readme_key(OLDEST): (
            b"---\nulid: 01OLDEST\nversion: 1\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\n"
        ),
    }
    for key, data in old_files.items():
        archive.store.write_atomic(key, data)
    before = _tree(archive)
    report = (
        "Rewritten: 2\n"
        "Already new: 2\n"
        f"Left as it is (unreadable): {ARTICLES.readme_key(BROKEN)}\n"
        f"Left as it is (no change record): {ARTICLES.readme_key(OLDEST)}\n"
        f"Left as it is (would not read the same): {COLLECTIONS.readme_key(ODD)}\n"
    )

    out = io.StringIO()
    with pytest.raises(CommandError, match=r"^Left as it is: 3$"):
        call_command("relayout_readmes", "--dry-run", stdout=out)
    assert out.getvalue() == report
    assert _tree(archive) == before

    out = io.StringIO()
    with pytest.raises(CommandError, match=r"^Left as it is: 3$"):
        call_command("relayout_readmes", stdout=out)
    assert out.getvalue() == report
    after = _tree(archive)
    assert after.keys() == before.keys()
    changed = {key for key in after if after[key] != before[key]}
    assert changed == {ARTICLES.readme_key(OLD), COLLECTIONS.readme_key(OLD_BESTAND)}

    out = io.StringIO()
    with pytest.raises(CommandError):
        call_command("relayout_readmes", stdout=out)
    assert out.getvalue().startswith("Rewritten: 0\nAlready new: 4\n")
