"""The page-text store: a file's pages are written once, no page text is refused by Postgres, and
a rebuild leaves every page vector on the current config."""

import io
from dataclasses import replace
from itertools import islice, product
from string import ascii_lowercase

import pytest
from django.contrib.postgres.search import SearchVectorField
from django.db import connection
from django.db.models import F, Func

from bundesarchiv.domain.models import ULID, Article, Collection, Lifecycle
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex, MediaText
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

pytestmark = pytest.mark.django_db

_HASH = "a" * 64


def _pages(content_hash: str = _HASH) -> list[tuple[int, str]]:
    return list(
        MediaText.objects.filter(content_hash=content_hash)
        .order_by("page")
        .values_list("page", "text")
    )


def test_pages_are_stored_from_one_and_a_second_store_changes_nothing() -> None:
    indexer.store_media_text(_HASH, ("Lager im Wald", ""))
    indexer.store_media_text(_HASH, ("anders", ""))

    assert _pages() == [(1, "Lager im Wald"), (2, "")]


def test_a_file_without_pages_stores_only_the_marker() -> None:
    indexer.store_media_text(_HASH, ())

    assert _pages() == [(0, "")]
    assert indexer.hashes_with_text([_HASH, "b" * 64]) == {_HASH}


@pytest.mark.parametrize("unstorable", ["\x00", "\ud800"])
def test_what_postgres_cannot_take_is_dropped_not_refused(unstorable: str) -> None:
    indexer.store_media_text(_HASH, (f"Fahr{unstorable}ten",))

    assert _pages() == [(1, "Fahrten")]


def test_an_oversized_page_is_cut_not_refused() -> None:
    words = ("".join(letters) for letters in product(ascii_lowercase, repeat=5))
    huge = " ".join(islice(words, 250_000))  # distinct words: a tsvector far over 1 MB

    indexer.store_media_text(_HASH, ("klein", huge))

    stored = MediaText.objects.get(content_hash=_HASH, page=2)
    assert stored.text == huge[: len(stored.text)]
    assert 0 < len(stored.text) < len(huge)


@pytest.mark.parametrize("stale", ["an old config_version", "no row at all"])
def test_a_rebuild_over_a_stale_index_recomputes_the_page_vectors(stale: str) -> None:
    """Page rows outlive the rebuild, so a config change must not leave their vectors behind."""
    store = InMemoryObjectStore()
    CollectionRepository(store).save(
        Collection(ulid=ULID("ROOT"), name="Wurzel", parent_id=None), 0, changed_by="tester"
    )
    repo = ArticleRepository(store)
    article = Article(
        ulid=ULID("01FOTO"), title="Foto", collection_id=ULID("ROOT"), lifecycle=Lifecycle.PUBLISHED
    )
    repo.save(article, 0, changed_by="tester")
    ref = repo.add_media(
        ULID("01FOTO"), "f.pdf", io.BytesIO(b"pdf")
    )  # rebuild keeps only named text
    repo.save(replace(article, media=(ref,)), 1, changed_by="tester")
    indexer.rebuild(store)
    indexer.store_media_text(ref.content_hash, ("Fahrten im Lager",))
    if stale == "no row at all":
        ArticleIndex.objects.all().delete()
    else:
        ArticleIndex.objects.update(config_version=indexer.CONFIG_VERSION - 1)
    with connection.cursor() as cursor:  # a config change; rolled back with the test
        cursor.execute(
            "CREATE OR REPLACE FUNCTION bundesarchiv_text_tsv(page_text text) RETURNS tsvector"
            " LANGUAGE sql IMMUTABLE AS $$ SELECT to_tsvector('simple', page_text) $$"
        )

    indexer.rebuild(store)

    fresh = Func(F("text"), function="bundesarchiv_text_tsv", output_field=SearchVectorField())
    ((stored, recomputed),) = MediaText.objects.annotate(fresh=fresh).values_list("tsv", "fresh")
    assert stored == recomputed
