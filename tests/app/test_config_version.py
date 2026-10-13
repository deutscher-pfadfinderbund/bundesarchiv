"""``ensure_index_current``: an index row stamped with another ``config_version`` forces a rebuild from canonical (ADR 0014 §3)."""

import pytest

from bundesarchiv.app.reindex import ensure_index_current
from bundesarchiv.domain.models import (
    Article,
    Collection,
    Lifecycle,
)
from bundesarchiv.index import indexer
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository


@pytest.fixture
def store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0, changed_by="tester"
    )
    ArticleRepository(store).save(
        Article(ulid="01FOTO", title="Foto", collection_id="ROOT", lifecycle=Lifecycle.PUBLISHED),
        0,
        changed_by="tester",
    )
    return store


@pytest.mark.django_db
def test_ensure_index_current_rebuilds_on_version_mismatch(store: InMemoryObjectStore) -> None:
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    ArticleIndex.objects.filter(ulid="01FOTO").update(config_version=indexer.CONFIG_VERSION - 1)

    rebuilt = ensure_index_current(store)

    assert rebuilt is True
    assert ArticleIndex.objects.get(ulid="01FOTO").config_version == indexer.CONFIG_VERSION


@pytest.mark.django_db
def test_ensure_index_current_noop_when_all_current(store: InMemoryObjectStore) -> None:
    indexer.rebuild(store)
    assert ensure_index_current(store) is False


@pytest.mark.django_db
def test_ensure_index_current_rebuilds_empty_index(store: InMemoryObjectStore) -> None:
    """An empty index is trivially current (nothing stale) -> no forced rebuild."""
    from bundesarchiv.index.models import ArticleIndex

    assert ArticleIndex.objects.count() == 0
    assert ensure_index_current(store) is False
