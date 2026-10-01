"""CollectionRepository behaviour, exercised through its interface over both the
in-memory ObjectStore fake and the LocalFs adapter — mirrors the Article conformance
pattern so both stores must satisfy the same contract.
"""

import threading
from pathlib import Path

import pytest
from tests._readmes import UNREADABLE_README

from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.persistence import collection_readme
from bundesarchiv.persistence._writer import history_key, readme_key
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository, StoredCollection
from bundesarchiv.persistence.errors import Conflict, NotFound, UnreadableReadme
from bundesarchiv.persistence.objectstore import ObjectStore


def _collection(ulid: str = "01J0", **overrides: object) -> Collection:
    defaults: dict[str, object] = {
        "ulid": ulid,
        "name": "Fotos",
        "parent_id": None,
        "audience": Audience(AudienceTier.MEMBERS),
    }
    defaults.update(overrides)
    return Collection(**defaults)  # type: ignore[arg-type]


# --- conformance suite (parametrized over both stores) ---------------------------


@pytest.fixture(params=["memory", "localfs"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> CollectionRepository:
    if request.param == "memory":
        store: ObjectStore = InMemoryObjectStore()
    else:
        store = LocalFsObjectStore(tmp_path)
    return CollectionRepository(store)


def test_save_then_load_round_trips_the_collection(repo: CollectionRepository) -> None:
    collection = _collection(
        parent_id="PARENT01",
        audience=Audience(AudienceTier.GROUPS, ("bundesfuehrung",)),
    )
    version = repo.save(collection, expected_version=0, changed_by="tester")
    assert version == 1
    loaded = repo.load("01J0")
    assert isinstance(loaded, StoredCollection)
    assert loaded.collection == collection
    assert loaded.version == 1


def test_load_missing_raises_not_found(repo: CollectionRepository) -> None:
    with pytest.raises(NotFound):
        repo.load("nope")


def test_stale_expected_version_raises_conflict(repo: CollectionRepository) -> None:
    repo.save(_collection(), expected_version=0, changed_by="tester")  # -> v1
    with pytest.raises(Conflict):
        repo.save(
            _collection(name="rename"), expected_version=0, changed_by="tester"
        )  # stale; store is at v1
    # the correct version wins and bumps to v2
    assert repo.save(_collection(name="rename"), expected_version=1, changed_by="tester") == 2


def test_version_increments_across_saves(repo: CollectionRepository) -> None:
    assert repo.save(_collection(), expected_version=0, changed_by="tester") == 1
    assert repo.save(_collection(name="a"), expected_version=1, changed_by="tester") == 2
    assert repo.save(_collection(name="b"), expected_version=2, changed_by="tester") == 3
    assert repo.load("01J0").version == 3


def test_unversioned_readme_loads_as_zero_then_saves_cleanly(repo: CollectionRepository) -> None:
    # Migration (ADR 0013): a README written before versioning has no `version:` key.
    # It must load as version 0, and a save at expected_version=0 must write version 1.
    repo._store.write_atomic("collections/01J0/README.md", b"---\nulid: 01J0\nname: Old\n---\n")
    loaded = repo.load("01J0")
    assert loaded.version == 0
    assert repo.save(_collection(name="Migrated"), expected_version=0, changed_by="tester") == 1
    assert repo.load("01J0").version == 1


def test_load_all_returns_every_saved_collection(repo: CollectionRepository) -> None:
    repo.save(_collection("01A", name="Alpha"), expected_version=0, changed_by="tester")
    repo.save(_collection("01B", name="Beta"), expected_version=0, changed_by="tester")
    loaded = repo.load_all()
    assert isinstance(loaded, tuple)
    # load_all returns plain Collections (no versions) — tree assembly needs no versions.
    assert {c.ulid for c in loaded} == {"01A", "01B"}
    assert all(isinstance(c, Collection) for c in loaded)


def test_load_all_returns_empty_tuple_when_no_collections(repo: CollectionRepository) -> None:
    assert repo.load_all() == ()


def test_keys_for_lists_history_before_the_readme_it_replaced(repo: CollectionRepository) -> None:
    repo.save(_collection(), expected_version=0, changed_by="tester")
    repo.save(_collection(name="Neu"), expected_version=1, changed_by="tester")
    assert [(key.key, key.write_once) for key in repo.keys_for("01J0")] == [
        (history_key("collections/01J0", 1), True),
        (readme_key("collections/01J0"), False),
    ]


@pytest.mark.parametrize("rotten", [b"no front matter", b"---\nname: F\xf6to\n---\n"])
def test_keys_for_marks_a_readme_that_does_not_decode(
    repo: CollectionRepository, rotten: bytes
) -> None:
    repo.save(_collection(), expected_version=0, changed_by="tester")
    assert all(key.readable for key in repo.keys_for("01J0"))
    repo._store.write_atomic(readme_key("collections/01J0"), rotten)
    assert [(key.key, key.readable) for key in repo.keys_for("01J0")] == [
        (readme_key("collections/01J0"), False)
    ]


def test_collection_without_parent_and_audience_round_trips(repo: CollectionRepository) -> None:
    collection = Collection(ulid="01J0", name="Root")
    repo.save(collection, expected_version=0, changed_by="tester")
    loaded = repo.load("01J0")
    assert loaded.collection == collection
    assert loaded.collection.parent_id is None
    assert loaded.collection.audience is None


def test_racing_saves_one_winner_one_conflict_readme_at_winner_version(
    repo: CollectionRepository,
) -> None:
    """Two threads save the same Collection at the same expected_version. The shared writer
    mutex (ADR 0013) serializes the check-then-write, so EXACTLY one wins and the other sees a
    stale version -> Conflict. Assert the README version ends at the winner's version + 1.

    A barrier releases both threads together to force the interleave through the mutex; the
    mutex makes the outcome deterministic once both are past the barrier, so there are no
    sleeps and no flakiness.
    """
    repo.save(_collection(), expected_version=0, changed_by="tester")  # store is now at v1
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    lock = threading.Lock()

    def attempt(name: str) -> None:
        barrier.wait()  # both threads arrive, then both race the save
        try:
            new_version = repo.save(_collection(name=name), expected_version=1, changed_by="tester")
            with lock:
                results[name] = new_version
        except Conflict as exc:
            with lock:
                results[name] = exc

    threads = [threading.Thread(target=attempt, args=(n,)) for n in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [v for v in results.values() if isinstance(v, int)]
    losers = [v for v in results.values() if isinstance(v, Conflict)]
    assert len(winners) == 1, f"expected exactly one winner, got {results}"
    assert len(losers) == 1, f"expected exactly one Conflict, got {results}"
    assert winners[0] == 2  # winner wrote v1 -> v2
    assert repo.load("01J0").version == 2
    # And the README front matter really carries v2.
    raw = repo._store.read(readme_key("collections/01J0")).decode("utf-8")
    _decoded, stored_version, _ = collection_readme.decode_collection(raw, ulid="01J0")
    assert stored_version == 2


@pytest.mark.parametrize("data", UNREADABLE_README)
def test_an_unreadable_readme_fails_load_and_save(repo: CollectionRepository, data: bytes) -> None:
    """A hand edit may break a README (ADR 0020): load and save refuse it as ``UnreadableReadme``,
    and the save writes nothing."""
    repo._store.write_atomic(readme_key("collections/01J0"), data)
    before = {key: repo._store.read(key) for key in repo._store.list()}
    with pytest.raises(UnreadableReadme):
        repo.load("01J0")
    with pytest.raises(UnreadableReadme):
        repo.save(_collection(), expected_version=1, changed_by="tester")
    assert {key: repo._store.read(key) for key in repo._store.list()} == before
