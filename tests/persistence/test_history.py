"""Version history and audit for both repositories (ADR 0019): a save keeps the README it replaces
under ``history/``, byte for byte, before it commits the new one, and every version names who
wrote it and when."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundesarchiv.domain.models import Article, Change, Collection, Version
from bundesarchiv.persistence._writer import history_key, readme_key
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError, Conflict
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

ULID = "01J0"


@dataclass(frozen=True)
class _Tree:
    """One repository's folder for ``ULID``. ``save(name, expected, changed_by)`` saves a record
    whose README differs by ``name``; ``change()`` loads the current change record. ``older`` is a
    README an older codec wrote at ``older_version``: it loads, but no current encode would produce
    these bytes."""

    folder: str
    save: Callable[[str, Version, str], Version]
    change: Callable[[], Change | None]
    older: bytes
    older_version: Version


def _articles(store: ObjectStore) -> _Tree:
    repo = ArticleRepository(store)
    return _Tree(
        folder=f"articles/{ULID}",
        save=lambda title, expected, by: repo.save(
            Article(ULID, title, "coll"), expected, changed_by=by
        ),
        change=lambda: repo.load(ULID).change,
        older=(
            b"---\nulid: 01J0\nversion: 4\ntitle: Alt\ncollection_id: coll\nlifecycle: draft\n"
            b"tags: []\nref_code: null\n---\nText"
        ),
        older_version=4,
    )


def _collections(store: ObjectStore) -> _Tree:
    repo = CollectionRepository(store)
    return _Tree(
        folder=f"collections/{ULID}",
        save=lambda name, expected, by: repo.save(Collection(ULID, name), expected, changed_by=by),
        change=lambda: repo.load(ULID).change,
        older=b"---\nulid: 01J0\nname: Alt\n---\n",  # written before versioning: version 0
        older_version=0,
    )


_KINDS = pytest.mark.parametrize("make", [_articles, _collections], ids=["article", "collection"])


@pytest.fixture(params=["memory", "localfs"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    return InMemoryObjectStore() if request.param == "memory" else LocalFsObjectStore(tmp_path)


def _snapshot(store: ObjectStore) -> dict[str, bytes]:
    return {key: store.read(key) for key in store.list()}


@_KINDS
def test_history_lives_beside_the_readme(store: ObjectStore, make: Callable[..., _Tree]) -> None:
    tree = make(store)
    tree.save("eins", 0, "tester")
    tree.save("zwei", 1, "tester")
    assert set(store.list(f"{tree.folder}/")) == {
        f"{tree.folder}/README.md",
        f"{tree.folder}/history/1.md",
    }


@_KINDS
def test_every_replaced_version_is_kept_byte_for_byte(
    store: ObjectStore, make: Callable[..., _Tree]
) -> None:
    tree = make(store)
    written = []
    for expected, name in enumerate(("eins", "zwei", "drei")):
        tree.save(name, expected, "tester")
        written.append(store.read(readme_key(tree.folder)))
    assert [store.read(history_key(tree.folder, version)) for version in (1, 2)] == written[:2]
    assert store.read(readme_key(tree.folder)) == written[2]


@_KINDS
def test_a_readme_an_older_codec_wrote_loads_and_is_kept_as_it_was(
    store: ObjectStore, make: Callable[..., _Tree]
) -> None:
    tree = make(store)
    store.write_atomic(readme_key(tree.folder), tree.older)
    assert tree.change() is None
    tree.save("neu", tree.older_version, "tester")
    assert store.read(history_key(tree.folder, tree.older_version)) == tree.older


@_KINDS
def test_a_stale_save_writes_nothing(store: ObjectStore, make: Callable[..., _Tree]) -> None:
    tree = make(store)
    tree.save("eins", 0, "tester")
    tree.save("zwei", 1, "tester")
    before = _snapshot(store)
    with pytest.raises(Conflict):
        tree.save("veraltet", 1, "tester")
    assert _snapshot(store) == before


@_KINDS
def test_a_history_file_holding_other_bytes_stops_the_save(
    store: ObjectStore, make: Callable[..., _Tree]
) -> None:
    # Two different READMEs claimed version 1 (a restored or hand-edited tree): committing would
    # drop the current one, which no history file holds. Same length, so only the bytes differ.
    tree = make(store)
    tree.save("eins", 0, "tester")
    current = store.read(readme_key(tree.folder))
    other = current.replace(b"eins", b"EINS")
    assert other != current and len(other) == len(current)
    store.create(history_key(tree.folder, 1), other)
    before = _snapshot(store)
    with pytest.raises(ArchiveError) as refused:
        tree.save("zwei", 1, "tester")
    assert not isinstance(refused.value, Conflict)  # not a stale form: nothing to re-apply
    assert _snapshot(store) == before


@_KINDS
def test_each_version_names_who_wrote_it_and_when(
    store: ObjectStore, make: Callable[..., _Tree]
) -> None:
    tree = make(store)
    before = datetime.now(UTC).replace(microsecond=0)
    tree.save("eins", 0, "anna")
    first = tree.change()
    tree.save("zwei", 1, "ben")
    assert first is not None and first.by == "anna"
    assert before <= first.at <= datetime.now(UTC)
    latest = tree.change()
    assert latest is not None and latest.by == "ben"


@_KINDS
def test_a_blank_author_is_refused_before_anything_is_written(
    store: ObjectStore, make: Callable[..., _Tree]
) -> None:
    tree = make(store)
    tree.save("eins", 0, "anna")
    before = _snapshot(store)
    with pytest.raises(ValueError):
        tree.save("zwei", 1, "")
    assert _snapshot(store) == before


class _PowerCut(Exception):
    pass


class _CutsOnce(InMemoryObjectStore):
    """A real in-memory store whose next write to ``cut`` dies the way a crash would, before any
    byte of it lands."""

    def __init__(self) -> None:
        super().__init__()
        self.cut: str | None = None

    def create(self, key: str, data: bytes) -> str:
        self._maybe_cut(key)
        return super().create(key, data)

    def write_atomic(self, key: str, data: bytes) -> str:
        self._maybe_cut(key)
        return super().write_atomic(key, data)

    def _maybe_cut(self, key: str) -> None:
        if key == self.cut:
            self.cut = None
            raise _PowerCut(key)


@_KINDS
@pytest.mark.parametrize("step", ["history", "commit"])
def test_a_crash_mid_save_loses_nothing_and_the_retry_goes_on(
    make: Callable[..., _Tree], step: str
) -> None:
    store = _CutsOnce()
    tree = make(store)
    tree.save("eins", 0, "tester")
    first = store.read(readme_key(tree.folder))
    store.cut = history_key(tree.folder, 1) if step == "history" else readme_key(tree.folder)
    with pytest.raises(_PowerCut):
        tree.save("zwei", 1, "tester")
    assert store.read(readme_key(tree.folder)) == first
    assert tree.save("zwei", 1, "tester") == 2
    assert store.read(history_key(tree.folder, 1)) == first
