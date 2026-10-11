"""Task 4.2 — the config_version startup check (ADR 0014 §3).

``ensure_index_current`` is the deploy/startup guard: any index row whose stored ``config_version``
does not match the current ``indexer.CONFIG_VERSION`` means the FTS config changed under it, so the
whole index must be rebuilt from canonical. The check itself is what is new (only the column existed
before Part 4.2). Exercised through the reindex helper the management command calls, so the command
stays a thin shell.
"""

import io
from dataclasses import replace

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


@pytest.mark.django_db
def test_ensure_index_current_recomputes_the_page_vectors(store: InMemoryObjectStore) -> None:
    """Page rows survive the rebuild, so a config change must not leave their vectors behind."""
    from django.contrib.postgres.search import SearchVectorField
    from django.db import connection
    from django.db.models import F, Func

    from bundesarchiv.index.models import ArticleIndex, MediaText

    repo = ArticleRepository(store)
    ref = repo.add_media("01FOTO", "f.pdf", io.BytesIO(b"pdf"))  # rebuild keeps only named text
    repo.save(replace(repo.load("01FOTO").article, media=(ref,)), 1, changed_by="tester")
    indexer.rebuild(store)
    indexer.store_media_text(ref.content_hash, ("Fahrten im Lager",))
    ArticleIndex.objects.update(config_version=indexer.CONFIG_VERSION - 1)
    with connection.cursor() as cursor:  # a config change; rolled back with the test
        cursor.execute(
            "CREATE OR REPLACE FUNCTION bundesarchiv_text_tsv(page_text text) RETURNS tsvector"
            " LANGUAGE sql IMMUTABLE AS $$ SELECT to_tsvector('simple', page_text) $$"
        )

    ensure_index_current(store)

    fresh = Func(F("text"), function="bundesarchiv_text_tsv", output_field=SearchVectorField())
    ((stored, recomputed),) = MediaText.objects.annotate(fresh=fresh).values_list("tsv", "fresh")
    assert stored == recomputed
