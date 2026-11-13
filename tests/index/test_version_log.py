"""The version log, ``ArticleVersion``: what ``index_article`` and ``rebuild`` keep in it, and what
``PostgresIndex.versions`` reads back."""

import io
from collections.abc import Callable
from dataclasses import replace

import pytest
from tests._articles import make_article
from tests._readmes import UNREADABLE_README

from bundesarchiv.domain.history import Difference, VersionEntry
from bundesarchiv.domain.models import ULID, Article, Collection, Lifecycle, Version
from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex, ArticleVersion
from bundesarchiv.index.refresh import PostgresIndex
from bundesarchiv.persistence._layout import ARTICLES
from bundesarchiv.persistence._writer import history_key
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import Busy, NotFound
from bundesarchiv.persistence.repository import ArticleRepository

pytestmark = pytest.mark.django_db

ROOT = ULID("ROOT")
FIRST, SECOND = ULID("01FIRST"), ULID("01SECOND")
# Valid names a codec might mangle: non-ASCII, percent, comma, inner and outer spaces.
_EDITORS = ("anna.k", "Zoë %20, Ben ", "ben.m", "carla")


class _Store(InMemoryObjectStore):
    """Refuses every access to the history of the Articles in ``sealed`` but to the keys in
    ``unsealed``; the first read of a key in ``flaky`` fails as a busy backend does."""

    sealed: frozenset[ULID] = frozenset()
    unsealed: frozenset[str] = frozenset()
    flaky: frozenset[str] = frozenset()

    def read(self, key: str) -> bytes:
        self._refuse(key)
        if key in self.flaky:
            self.flaky -= {key}
            raise Busy(key)
        return super().read(key)

    def list(self, prefix: str = "") -> list[str]:
        self._refuse(prefix)
        return list(super().list(prefix))

    def _refuse(self, key: str) -> None:
        if key not in self.unsealed and any(
            key.startswith(f"{ARTICLES.folder(ulid)}/history/") for ulid in self.sealed
        ):
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


def _on_file(store: _Store, ulid: ULID) -> tuple[VersionEntry, ...]:
    articles = ArticleRepository(store)
    return articles.versions(articles.load(ulid))


def _logged(store: _Store, ulid: ULID) -> tuple[VersionEntry, ...]:
    return PostgresIndex(store).versions(ulid)


def _history(ulid: ULID, version: int) -> str:
    return history_key(ARTICLES.folder(ulid), version)


def _seal(store: _Store, *ulids: ULID, but: Version | None = None) -> None:
    """Seals the history of ``ulids`` but the kept version ``but`` of each; no ``ulids``
    unseals."""
    store.sealed = frozenset(ulids)
    store.unsealed = frozenset(() if but is None else (_history(ulid, but) for ulid in ulids))


def test_a_refresh_logs_every_version_with_its_change_record(store: _Store) -> None:
    _save(store, FIRST, *_EDITORS)
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == _on_file(store, FIRST)
    assert [entry.version for entry in _logged(store, FIRST)] == [1, 2, 3, 4]


def test_reading_the_versions_reads_no_file(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    assert [entry.version for entry in PostgresIndex(_Store()).versions(FIRST)] == [1, 2]


def test_a_kept_version_without_a_readable_change_record_keeps_its_number(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    store.write_atomic(_history(FIRST, 1), b"\xff\xfe\x00")
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST)[0] == VersionEntry(1, None, Difference())
    assert _logged(store, FIRST) == _on_file(store, FIRST)


def test_a_refresh_after_a_save_reads_only_the_version_before(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    indexer.index_article(store, FIRST)
    _save(store, FIRST, "carla")
    _seal(store, FIRST, but=2)
    indexer.index_article(store, FIRST)
    _seal(store)
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
    assert [entry.version for entry in _logged(store, FIRST)] == [1, 3]
    _seal(store, FIRST, but=2)
    indexer.index_article(store, FIRST)
    _seal(store)
    _save(store, FIRST, "anna.k")
    _seal(store, FIRST, but=3)
    indexer.index_article(store, FIRST)
    _seal(store)
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
    ArticleVersion.objects.filter(ulid=FIRST).update(changed_by="nobody", difference=None)
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
    _seal(store, FIRST)
    indexer.rebuild(store)
    _seal(store)
    assert _logged(store, FIRST) == _on_file(store, FIRST)
    assert _logged(store, SECOND) == _on_file(store, SECOND)
    assert _logged(store, gone) == ()


def test_unknown_and_nothing_changed_are_logged_apart(store: _Store) -> None:
    _save(store, FIRST, "anna.k", "ben.m")
    store.write_atomic(_history(FIRST, 1), b"\xff\xfe\x00")
    indexer.index_article(store, FIRST)
    assert [entry.difference for entry in _logged(store, FIRST)] == [Difference(), None]


_REFRESHES = pytest.mark.parametrize(
    "refresh",
    [
        pytest.param(lambda store: indexer.index_article(store, FIRST), id="index_article"),
        pytest.param(indexer.rebuild, id="rebuild"),
    ],
)

#: Names a codec might split, escape or trim: its delimiters, quotes, unicode, percent, spaces.
_NAMES = (' Zoë %20, "x" ', "[a]{b}\\c:d", "Ölzeug, 1975", "\N{EN DASH}  ")


@_REFRESHES
def test_what_changed_is_logged_as_the_files_say(
    store: _Store, refresh: Callable[[_Store], object]
) -> None:
    articles = ArticleRepository(store)
    files = [articles.add_media(FIRST, f"{name}.pdf", io.BytesIO(name.encode())) for name in _NAMES]
    first = make_article(
        FIRST,
        collection_id=ROOT,
        lifecycle=Lifecycle.DRAFT,
        media=(files[0],),
        custom=(("alt", "1"),),
    )
    articles.save(first, 0, changed_by="anna.k")
    articles.save(
        replace(
            first,
            lifecycle=Lifecycle.PUBLISHED,
            media=tuple(files[1:]),
            custom=tuple((name, name) for name in _NAMES),
        ),
        1,
        changed_by="ben.m",
    )
    stored = articles.load(FIRST)
    articles.mark_deleted(stored.article, stored.version, changed_by="carla")
    refresh(store)
    logged = _logged(store, FIRST)
    assert logged == _on_file(store, FIRST)
    published = logged[1].difference
    assert published is not None
    assert published.custom == {"alt", *_NAMES}
    assert [name for _, name in published.added] == [ref.filename for ref in files[1:]]


@_REFRESHES
def test_what_postgres_cannot_store_is_left_out_of_a_kept_name(
    store: _Store, refresh: Callable[[_Store], object]
) -> None:
    articles = ArticleRepository(store)
    first = make_article(FIRST, collection_id=ROOT)
    articles.save(first, 0, changed_by="anna.k")
    plan = articles.add_media(FIRST, "pl\x00an.pdf", io.BytesIO(b"plan"))
    articles.save(
        replace(first, media=(plan,), custom=(("Kis\x00te", "3"),)), 1, changed_by="ben.m"
    )
    articles.save(first, 2, changed_by="carla")
    refresh(store)
    file = ((plan.content_hash, "plan.pdf"),)
    key, media = frozenset({"Kiste"}), frozenset({"media"})
    assert [entry.difference for entry in _logged(store, FIRST)] == [
        Difference(),
        Difference(fields=media, custom=key, added=file),
        Difference(fields=media, custom=key, removed=file),
    ]


def test_a_store_error_on_the_version_before_fails_the_refresh_and_logs_it_on_retry(
    store: _Store,
) -> None:
    _save(store, FIRST, "anna.k")
    indexer.index_article(store, FIRST)
    _save(store, FIRST, "ben.m")
    store.flaky = frozenset({_history(FIRST, 1)})
    with pytest.raises(Busy):
        indexer.index_article(store, FIRST)
    assert [entry.version for entry in _logged(store, FIRST)] == [1]
    indexer.index_article(store, FIRST)
    assert _logged(store, FIRST) == _on_file(store, FIRST)
