"""The ``Archive`` handle: one construction site for the canonical store (ADR 0005)."""

from pathlib import Path

from django.test import override_settings

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import ULID, Article
from bundesarchiv.index.refresh import InMemoryIndex
from bundesarchiv.persistence.objectstore import ObjectStore

ARTICLE_ULID = ULID("01KX7YT9E3VX0CP3A5Q49RZMWK")


def test_canonical_resolves_the_configured_root_at_every_call(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(first)):
        Archive.canonical().articles.save(
            Article(ulid=ARTICLE_ULID, title="Sommerfahrt", collection_id=ULID("ROOT")),
            0,
            changed_by="tester",
        )

    assert (first / "articles" / ARTICLE_ULID / "README.md").is_file()
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(second)):
        assert list(Archive.canonical().articles.list_ulids()) == []


def test_the_index_is_built_over_the_archives_own_store(tmp_path: Path) -> None:
    """ADR 0024."""
    over: list[ObjectStore] = []

    def index(store: ObjectStore) -> InMemoryIndex:
        over.append(store)
        return InMemoryIndex(store)

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path), BUNDESARCHIV_INDEX=index):
        archive = Archive.canonical()

    assert over == [archive.store]
