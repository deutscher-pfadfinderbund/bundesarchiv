"""The version log, ``ArticleVersion``: what ``index_article`` and ``rebuild`` keep in it, and what
``PostgresIndex.versions`` reads back."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests._articles import make_article
from tests._readmes import UNREADABLE_README

from bundesarchiv.domain.models import ULID, Article, Change, Collection, Version
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex, ArticleVersion
from bundesarchiv.index.refresh import PostgresIndex
from bundesarchiv.persistence._layout import ARTICLES
from bundesarchiv.persistence._writer import history_key
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.repository import ArticleRepository

pytestmark = pytest.mark.django_db

ROOT = ULID("ROOT")
FIRST, SECOND = ULID("01FIRST"), ULID("01SECOND")
# Valid names a codec might mangle: non-ASCII, percent, comma, inner and outer spaces.
_EDITORS = ("anna.k", "Zoë %20, Ben ", "ben.m", "carla")


class _Store(InMemoryObjectStore):
    """Refuses every access to the history of the Articles in ``sealed``."""

    sealed: frozenset[ULID] = frozenset()

    def read(self, key: str) -> bytes:
        self._refuse(key)
        return super().read(key)

    def list(self, prefix: str = "") -> list[str]:
        self._refuse(prefix)
        return list(super().list(prefix))

    def _refuse(self, key: str) -> None:
        if any(key.startswith(f"{ARTICLES.folder(ulid)}/history/") for ulid in self.sealed):
            raise AssertionError(f"read the history: {key}")


@pytest.fixture
def store() -> _Store:
    store = _Store()
    CollectionRepository(store).save(Collection(ROOT, "Wurzel", None), 0, changed_by="tester")
    return store


def _save(store: _Store, ulid: ULID, *editors: str) -> None:
    """Saves the next versions of ``ulid``, one per editor."""
    articles = ArticleRepository(store)
    try:
        stored = articles.load(ulid)
        article, version = stored.article, stored.version
    except NotFound:
        article, version = make_article(ulid, collection_id=ROOT), 0
    for editor in editors:
        version = articles.save(_changed(article, version), version, changed_by=editor)


def _changed(article: Article, version: Version) -> Article:
    return replace(article, title=f"Titel {version + 1}")


def _on_file(store: _Store, ulid: ULID) -> tuple[tuple[Version, Change | None], ...]:
    articles = ArticleRepository(store)
    return articles.versions(articles.load(ulid))


def _logged(store: _Store, ulid: ULID) -> tuple[tuple[Version, Change | None], ...]:
    return PostgresIndex(store).versions(ulid)


def _history(ulid: ULID, version: int) -> str:
    return history_key(ARTICLES.folder(ulid), version)


def test_a_refresh_logs_every_version_with_its_change_record(store: _Store) -> None:
    _save(store, FIRST, *_EDITORS)
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == _on_file(store, FIRST)
    assert [number for number, _ in _logged(store, FIRST)] == [1, 2, 3, 4]


def test_reading_the_versions_reads_no_file(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    assert [number for number, _ in PostgresIndex(_Store()).versions(FIRST)] == [1, 2]


def test_a_kept_version_without_a_readable_change_record_keeps_its_number(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    store.write_atomic(_history(FIRST, 1), b"\xff\xfe\x00")
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST)[0] == (1, None)
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_refresh_after_a_save_reads_no_history(store: _Store) -> None:
    _save(store, FIRST, "anna.k")
    indexer.index_article(store, FIRST)
    _save(store, FIRST, "ben.m")
    store.sealed = frozenset({FIRST})
    indexer.index_article(store, FIRST)
    store.sealed = frozenset()
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_refresh_fills_the_versions_a_missed_refresh_left_out(store: _Store) -> None:
    _save(store, FIRST, "anna.k")
    indexer.index_article(store, FIRST)
    _save(store, FIRST, "ben.m", "carla")
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_gap_in_the_history_is_read_once(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m", "carla")
    store.delete(_history(FIRST, 2))
    indexer.index_article(store, FIRST)
    assert [number for number, _ in _logged(store, FIRST)] == [1, 3]
    store.sealed = frozenset({FIRST})
    indexer.index_article(store, FIRST)
    store.sealed = frozenset()
    _save(store, FIRST, "anna.k")
    store.sealed = frozenset({FIRST})
    indexer.index_article(store, FIRST)
    store.sealed = frozenset()
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_an_article_gone_loses_its_versions(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    ArticleRepository(store).hard_delete(FIRST, 2)
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == ()


@pytest.mark.parametrize("readme", UNREADABLE_README)
def test_an_unreadable_readme_keeps_the_versions_logged(store: _Store, readme: bytes) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    logged = _logged(store, FIRST)
    store.write_atomic(ARTICLES.readme_key(FIRST), readme)
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == logged


@pytest.mark.parametrize(
    "refresh",
    [
        pytest.param(lambda store: indexer.index_article(store, FIRST), id="index_article"),
        pytest.param(indexer.rebuild, id="rebuild"),
    ],
)
def test_a_tree_set_back_to_an_earlier_version_drops_the_later_ones(
    store: _Store, refresh: Callable[[_Store], object]
) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    earlier = store.read(ARTICLES.readme_key(FIRST))
    _save(store, FIRST, "carla")
    indexer.index_article(store, FIRST)
    store.write_atomic(ARTICLES.readme_key(FIRST), earlier)
    store.delete(_history(FIRST, 2))
    refresh(store)
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_version_set_back_and_saved_again_is_logged_as_the_files_say(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    earlier = store.read(ARTICLES.readme_key(FIRST))
    _save(store, FIRST, "carla")
    indexer.index_article(store, FIRST)
    store.write_atomic(ARTICLES.readme_key(FIRST), earlier)
    store.delete(_history(FIRST, 2))
    _save(store, FIRST, "dora")
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_rebuild_over_a_stale_config_logs_every_version_anew(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.rebuild(store)
    ArticleVersion.objects.filter(ulid=FIRST, version=1).update(changed_by="nobody")
    ArticleIndex.objects.update(config_version=indexer.CONFIG_VERSION - 1)
    indexer.rebuild(store)
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_rebuild_fills_what_is_missing_and_drops_what_is_gone(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    gone = ULID("01GONE")
    _save(store, gone, "anna.k")
    indexer.index_article(store, gone)
    ArticleRepository(store).hard_delete(gone, 1)
    _save(store, SECOND, "anna.k", "ben.m", "carla")
    store.sealed = frozenset({FIRST})
    indexer.rebuild(store)
    store.sealed = frozenset()
    assert _logged(store, FIRST) == _on_file(store, FIRST)
    assert _logged(store, SECOND) == _on_file(store, SECOND)
    assert _logged(store, gone) == ()
