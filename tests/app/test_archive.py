"""The ``Archive`` handle: one construction site for the canonical store (ADR 0005)."""

from pathlib import Path

from django.test import override_settings

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.models import Article, Collection
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

ULID = "01KX7YT9E3VX0CP3A5Q49RZMWK"


def test_of_wires_both_repositories_over_the_given_store() -> None:
    store = InMemoryObjectStore()
    archive = Archive.of(store)

    archive.collections.save(
        Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0, changed_by="tester"
    )
    archive.articles.save(
        Article(ulid=ULID, title="Sommerfahrt", collection_id="ROOT"), 0, changed_by="tester"
    )

    assert CollectionRepository(store).load("ROOT").collection.name == "Wurzel"
    assert ArticleRepository(store).load(ULID).article.title == "Sommerfahrt"


def test_canonical_resolves_the_configured_root_at_every_call(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(first)):
        Archive.canonical().articles.save(
            Article(ulid=ULID, title="Sommerfahrt", collection_id="ROOT"), 0, changed_by="tester"
        )

    assert (first / "articles" / ULID / "README.md").is_file()
    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(second)):
        assert list(Archive.canonical().articles.list_ulids()) == []
