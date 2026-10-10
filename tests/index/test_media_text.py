"""The page-text store: a file's pages are written once, whole or not at all, and no page text
is refused by Postgres."""

from itertools import islice, product
from string import ascii_lowercase

import pytest

from bundesarchiv.index import indexer
from bundesarchiv.index.models import MediaText

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


def test_nul_never_reaches_postgres() -> None:
    indexer.store_media_text(_HASH, ("Fahr\x00ten",))

    assert _pages() == [(1, "Fahrten")]


def test_an_oversized_page_is_cut_not_refused() -> None:
    words = ("".join(letters) for letters in product(ascii_lowercase, repeat=5))
    huge = " ".join(islice(words, 250_000))  # distinct words: a tsvector far over 1 MB

    indexer.store_media_text(_HASH, ("klein", huge))

    stored = MediaText.objects.get(content_hash=_HASH, page=2)
    assert stored.text == huge[: len(stored.text)]
    assert 0 < len(stored.text) < len(huge)


@pytest.mark.django_db(transaction=True)  # autocommit, as the worker runs: no outer rollback
def test_an_interrupted_store_leaves_no_rows() -> None:
    with pytest.raises(UnicodeEncodeError):
        indexer.store_media_text(_HASH, ("eins", "zwei", "\ud800"))

    assert _pages() == []
