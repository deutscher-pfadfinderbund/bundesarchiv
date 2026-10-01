"""A query that equals an Article's Signatur puts that Article first under relevance order,
whatever the case or spacing, and never past what the viewer may see.

Its own module and corpus, because ``indexer.rebuild`` wipes the table (see ``test_leaks_decades.py``).
"""

from collections.abc import Iterator

import pytest
from tests._articles import make_article
from tests.index import fixtures

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist, Public, Viewer
from bundesarchiv.index import indexer
from bundesarchiv.index.query import search
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_PUBLIC = Public()
_OPEN = "SG_OPEN"
_CLOSED = "SG_CLOSED"


def _articles() -> tuple[Article, ...]:
    return (
        # The decoys say "BA 10" far more often than the real record does.
        make_article("SG_DECOY", collection_id=_OPEN, title="BA 10 BA 10 BA 10 Rundbrief"),
        make_article("SG_BA10", collection_id=_OPEN, title="Akte", ref_code="BA 10"),
        make_article("SG_BA2", collection_id=_OPEN, title="Akte", ref_code="BA 2"),
        make_article("SG_DUP1", collection_id=_OPEN, title="Akte", ref_code="BA B266"),
        make_article("SG_DUP2", collection_id=_OPEN, title="Akte", ref_code="BA B266"),
        make_article("SG_DUP_DECOY", collection_id=_OPEN, title="BA B266 BA B266 BA B266"),
        make_article("SG_SECRET", collection_id=_CLOSED, title="Akte", ref_code="BA 77"),
    )


def _build_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    collections = CollectionRepository(store)
    collections.save(
        Collection(_OPEN, "Offen", audience=Audience(AudienceTier.PUBLIC)), 0, changed_by="t"
    )
    collections.save(
        Collection(_CLOSED, "Zu", audience=Audience(AudienceTier.MEMBERS)), 0, changed_by="t"
    )
    repo = ArticleRepository(store)
    for article in _articles():
        repo.save(article, 0, changed_by="t")
    return store


@pytest.fixture(scope="module")
def _indexed(
    django_db_setup: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[indexer.RebuildReport]:
    yield from fixtures.indexed_corpus(django_db_blocker, lambda: indexer.rebuild(_build_store()))


@pytest.fixture
def corpus(_indexed: indexer.RebuildReport, db: None) -> None:
    """Per-test entry: joins the module-indexed corpus to the ``db`` transaction fixture."""


def _first(text: str, n: int = 1, viewer: Viewer = _PUBLIC) -> list[str]:
    return [h.ulid for h in search(viewer, text=text).hits[:n]]


@pytest.mark.django_db
@pytest.mark.parametrize("text", ["BA 10", "BA10", "ba 10", " ba   10 ", "Ba10"])
def test_the_typed_signatur_finds_its_article_first(corpus: None, text: str) -> None:
    assert _first(text) == ["SG_BA10"]


@pytest.mark.django_db
def test_a_signatur_is_matched_whole_not_as_a_prefix(corpus: None) -> None:
    assert "SG_BA10" not in [h.ulid for h in search(Public(), text="BA 1").hits[:1]]


@pytest.mark.django_db
def test_articles_sharing_a_signatur_all_come_first(corpus: None) -> None:
    assert set(_first("BA B266", 2)) == {"SG_DUP1", "SG_DUP2"}


@pytest.mark.django_db
def test_an_exact_signatur_never_reveals_an_article_the_viewer_cannot_see(corpus: None) -> None:
    page = search(Public(), text="BA 77")
    assert "SG_SECRET" not in {h.ulid for h in page.hits}
    assert "SG_SECRET" in {h.ulid for h in search(Archivist(), text="BA77").hits}
