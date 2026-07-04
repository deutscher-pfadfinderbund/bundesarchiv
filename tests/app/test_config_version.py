"""Task 4.2 — the config_version startup check (ADR 0014 §3).

``ensure_index_current`` is the deploy/startup guard: any index row whose stored ``config_version``
does not match the current ``indexer.CONFIG_VERSION`` means the FTS config changed under it, so the
whole index must be rebuilt from canonical. The check itself is what is new (only the column existed
before Part 4.2). Exercised through the reindex helper the management command calls, so the command
stays a thin shell.
"""

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
    CollectionRepository(store).save(Collection(ulid="ROOT", name="Wurzel", parent_id=None), 0)
    ArticleRepository(store).save(
        Article(ulid="01FOTO", title="Foto", collection_id="ROOT", lifecycle=Lifecycle.PUBLISHED),
        0,
    )
    return store


@pytest.mark.django_db
def test_ensure_index_current_rebuilds_on_version_mismatch(store: InMemoryObjectStore) -> None:
    """A stale-config_version row triggers a rebuild that restamps the current version."""
    from bundesarchiv.index.models import ArticleIndex

    indexer.rebuild(store)
    ArticleIndex.objects.filter(ulid="01FOTO").update(config_version=indexer.CONFIG_VERSION - 1)

    rebuilt = ensure_index_current(store)

    assert rebuilt is True
    assert ArticleIndex.objects.get(ulid="01FOTO").config_version == indexer.CONFIG_VERSION


@pytest.mark.django_db
def test_ensure_index_current_noop_when_all_current(store: InMemoryObjectStore) -> None:
    """No mismatch -> no rebuild (returns False)."""
    indexer.rebuild(store)
    assert ensure_index_current(store) is False


@pytest.mark.django_db
def test_ensure_index_current_rebuilds_empty_index(store: InMemoryObjectStore) -> None:
    """An empty index is trivially current (nothing stale) -> no forced rebuild."""
    from bundesarchiv.index.models import ArticleIndex

    assert ArticleIndex.objects.count() == 0
    assert ensure_index_current(store) is False
