"""Schlagwort suggestions (``query.suggest_tags``): which tags a typed text offers, in what order.

Its own module and corpus, because ``indexer.rebuild`` wipes the table.
"""

from collections.abc import Iterator

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Public
from bundesarchiv.index import indexer
from bundesarchiv.index.query import suggest_tags
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_ROOT = "TS_ROOT"

#: Each row one Article's tags. Uses: Stoffwappen 3, Ärmelwappen 2, Wappenkunde 2, Wappenbuch 1.
_TAGS: tuple[tuple[str, ...], ...] = (
    ("Stoffwappen", "Geschichte"),
    ("Stoffwappen", "Ärmelwappen", "Wappenkunde"),
    ("Stoffwappen", "Ärmelwappen", "Dritte, umgearbeitete Auflage, 1924"),
    ("Wappenkunde", "Wappenbuch"),
    tuple(f"Lager {n:02}" for n in range(1, 13)),
)


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection(_ROOT, "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="tester"
    )
    repo = ArticleRepository(store)
    for i, tags in enumerate(_TAGS):
        repo.save(make_article(f"TS_{i}", collection_id=_ROOT, tags=tags), 0, changed_by="anna")
    draft = make_article(
        "TS_DRAFT", collection_id=_ROOT, lifecycle=Lifecycle.DRAFT, tags=("Wappenrolle",)
    )
    repo.save(draft, 0, changed_by="anna")
    marked = make_article("TS_MARKED", collection_id=_ROOT, tags=("Wappenfund",))
    repo.mark_deleted(marked, repo.save(marked, 0, changed_by="anna"), changed_by="bernd")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


@pytest.mark.usefixtures("corpus")
def test_tags_starting_with_the_text_come_first_then_by_use_then_alphabetically() -> None:
    assert suggest_tags(Archivist(), " WAPPEN ") == (
        "Wappenkunde",
        "Wappenbuch",
        "Wappenrolle",
        "Stoffwappen",
        "Ärmelwappen",
    )


@pytest.mark.usefixtures("corpus")
def test_a_tag_already_on_the_article_is_not_suggested() -> None:
    assert suggest_tags(Archivist(), "wappen", exclude=("Stoffwappen", "Wappenbuch")) == (
        "Wappenkunde",
        "Wappenrolle",
        "Ärmelwappen",
    )


@pytest.mark.usefixtures("corpus")
def test_at_most_ten_whole_tags_and_nothing_for_no_text() -> None:
    assert suggest_tags(Archivist(), "lager") == tuple(f"Lager {n:02}" for n in range(1, 11))
    assert suggest_tags(Archivist(), "auflage,") == ("Dritte, umgearbeitete Auflage, 1924",)
    assert suggest_tags(Archivist(), "  ") == ()


@pytest.mark.usefixtures("corpus")
def test_a_viewer_is_offered_only_the_tags_of_articles_they_see() -> None:
    assert "Wappenrolle" not in suggest_tags(Public(), "wappen")
