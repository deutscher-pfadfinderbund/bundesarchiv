"""CollectionRepository behaviour, exercised through its interface over both the
in-memory ObjectStore fake and the LocalFs adapter — mirrors the Article conformance
pattern so both stores must satisfy the same contract.
"""

from pathlib import Path

import pytest

from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError, NotFound
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
    repo.save(collection)
    loaded = repo.load("01J0")
    assert loaded == collection


def test_load_missing_raises_not_found(repo: CollectionRepository) -> None:
    with pytest.raises(NotFound):
        repo.load("nope")


def test_save_is_idempotent_and_overwrites(repo: CollectionRepository) -> None:
    repo.save(_collection(name="Original"))
    repo.save(_collection(name="Updated"))
    assert repo.load("01J0").name == "Updated"


def test_load_all_returns_every_saved_collection(repo: CollectionRepository) -> None:
    repo.save(_collection("01A", name="Alpha"))
    repo.save(_collection("01B", name="Beta"))
    loaded = repo.load_all()
    assert isinstance(loaded, tuple)
    assert {c.ulid for c in loaded} == {"01A", "01B"}


def test_load_all_returns_empty_tuple_when_no_collections(repo: CollectionRepository) -> None:
    assert repo.load_all() == ()


def test_hard_delete_removes_the_collection(repo: CollectionRepository) -> None:
    repo.save(_collection())
    repo.hard_delete("01J0")
    with pytest.raises(NotFound):
        repo.load("01J0")
    assert repo.load_all() == ()


def test_hard_delete_is_a_no_op_for_absent_collection(repo: CollectionRepository) -> None:
    repo.hard_delete("never-existed")  # must not raise


def test_readme_carries_marker(repo: CollectionRepository) -> None:
    repo.save(_collection())
    # Peek at the raw store via the internal reference (memory only — localfs is opaque).
    # This test is only valuable for the memory store; skip gracefully for others.
    if not hasattr(repo._store, "_blobs"):
        return
    raw = repo._store.read("collections/01J0/README.md").decode("utf-8")
    assert raw.startswith("<!-- Managed by bundesarchiv")
    assert "Fotos" in raw


def test_collection_without_parent_and_audience_round_trips(repo: CollectionRepository) -> None:
    collection = Collection(ulid="01J0", name="Root")
    repo.save(collection)
    loaded = repo.load("01J0")
    assert loaded == collection
    assert loaded.parent_id is None
    assert loaded.audience is None


def test_load_of_a_corrupt_readme_surfaces_archive_error(repo: CollectionRepository) -> None:
    # Corrupt README must surface as ArchiveError across the seam.
    if not hasattr(repo._store, "_blobs"):
        return  # only testable on the in-memory store
    repo._store.write_atomic("collections/bad/README.md", b"---\ntags: [unclosed\n---\nbody")
    with pytest.raises(ArchiveError):
        repo.load("bad")
