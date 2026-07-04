"""ArticleRepository behaviour, exercised through its interface over both the
in-memory ObjectStore fake and the LocalFs adapter (the Collection conformance
pattern) — the canonical-file protocol, optimistic concurrency, content-addressed
write-once media, and recoverable hard_delete.
"""

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle
from bundesarchiv.persistence import readme
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository


@pytest.fixture(params=["memory", "localfs"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> ArticleRepository:
    # Parametrized over both stores: the racing test in particular MUST run against
    # localfs — the in-memory critical section has no IO yield point, so under the GIL
    # it cannot lose the race even with the lock neutralized; only real file IO between
    # the version check and the commit makes the race honest.
    if request.param == "memory":
        store: ObjectStore = InMemoryObjectStore()
    else:
        store = LocalFsObjectStore(tmp_path)
    return ArticleRepository(store)


def _article(ulid: str = "01J0", **overrides: object) -> Article:
    defaults: dict[str, object] = {
        "ulid": ulid,
        "title": "Zeltlager 1955",
        "collection_id": "coll-fotos",
        "body": "Ein Foto vom Zeltlager.\n\n## Details\n\n---\n\nSchwarz-weiß.",
        "lifecycle": Lifecycle.PUBLISHED,
        "audience": Audience(AudienceTier.GROUPS, ("bundesfuehrung",)),
        "ref_code": "Foto-1955/007",
        "tags": ("zeltlager", "1955"),
        "physical_location": "Magazin 2 / Regal B / Mappe 14",
    }
    defaults.update(overrides)
    return Article(**defaults)  # type: ignore[arg-type]


def test_save_then_load_round_trips_the_article(repo: ArticleRepository) -> None:
    article = _article()
    version = repo.save(article, expected_version=0)
    assert version == 1
    loaded = repo.load("01J0")
    assert loaded.article == article  # every field, incl. German body with a --- rule
    assert loaded.version == 1


def test_load_missing_raises_not_found(repo: ArticleRepository) -> None:
    with pytest.raises(NotFound):
        repo.load("nope")


def test_stale_expected_version_raises_conflict(repo: ArticleRepository) -> None:
    repo.save(_article(), expected_version=0)  # -> v1
    with pytest.raises(Conflict):
        repo.save(_article(title="rename"), expected_version=0)  # stale; store is at v1
    assert repo.save(_article(title="rename"), expected_version=1) == 2  # correct version wins


def test_readme_carries_marker_and_is_the_commit_point(repo: ArticleRepository) -> None:
    repo.save(_article(), expected_version=0)
    raw = repo._store.read("articles/01J0/README.md").decode("utf-8")
    assert raw.startswith("<!-- Managed by bundesarchiv")
    assert "Zeltlager 1955" in raw


def test_list_ulids_returns_articles_not_media_or_changes(repo: ArticleRepository) -> None:
    repo.save(_article("01A"), expected_version=0)
    repo.save(_article("01B"), expected_version=0)
    assert set(repo.list_ulids()) == {"01A", "01B"}


def test_add_media_is_content_addressed_and_write_once(repo: ArticleRepository) -> None:
    first = repo.add_media("01J0", "photo.jpg", b"the bytes", media_type="image/jpeg")
    again = repo.add_media("01J0", "renamed.jpg", b"the bytes")  # same bytes
    assert first.content_hash == again.content_hash  # content-addressed
    assert first.byte_size == len(b"the bytes")
    # write-once: only one blob on the store, keyed by the hash
    assert set(repo._store.list("articles/01J0/media/")) == {
        f"articles/01J0/media/{first.content_hash}"
    }


def test_save_refuses_readme_referencing_unstored_media(repo: ArticleRepository) -> None:
    # The pinned order is media -> README. Referencing media that was never stored
    # must fail rather than commit a README that points at nothing.
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    orphan = type(ref)(filename="ghost.jpg", content_hash="0" * 64)
    with pytest.raises(ArchiveError):
        repo.save(_article(media=(orphan,)), expected_version=0)
    # the real one is fine
    assert repo.save(_article(media=(ref,)), expected_version=0) == 1


def test_hard_delete_removes_article_but_keeps_recoverable_copy(repo: ArticleRepository) -> None:
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    repo.save(_article(media=(ref,)), expected_version=0)
    original = set(repo._store.list("articles/01J0/"))
    assert len(original) == 3  # README + the media blob + the v1 changes record

    repo.hard_delete("01J0")

    with pytest.raises(NotFound):
        repo.load("01J0")
    assert list(repo.list_ulids()) == []  # gone from listings
    # recoverable: the ENTIRE subtree (README, media, changes) lives under reserved .trash,
    # excluded from list() — not just the README.
    for key in original:
        assert repo._store.exists(f".trash/{key}") is True
    assert set(repo._store.list()) == set()


def test_hard_delete_is_a_no_op_for_absent_article(repo: ArticleRepository) -> None:
    repo.hard_delete("never-existed")  # must not raise


def test_load_of_a_corrupt_readme_surfaces_archive_error(repo: ArticleRepository) -> None:
    # Integration: a damaged README must reach the caller as ArchiveError (the codec's
    # detailed corrupt-input cases are covered directly in test_readme.py).
    repo._store.write_atomic("articles/bad/README.md", b"---\ntags: [unclosed\n---\nbody")
    with pytest.raises(ArchiveError):
        repo.load("bad")


def test_update_applies_mutation_and_bumps_version(repo: ArticleRepository) -> None:
    repo.save(_article(lifecycle=Lifecycle.DRAFT), expected_version=0)  # v1
    new_version = repo.update("01J0", lambda a: replace(a, lifecycle=Lifecycle.PUBLISHED))
    assert new_version == 2
    assert repo.load("01J0").article.lifecycle is Lifecycle.PUBLISHED


def test_update_on_absent_article_raises_not_found(repo: ArticleRepository) -> None:
    with pytest.raises(NotFound):
        repo.update("nope", lambda a: a)


def test_update_retries_on_a_concurrent_conflict(repo: ArticleRepository) -> None:
    # A REAL conflict (no mocking): the mutate fn sneaks a concurrent save on its first
    # call, bumping the version so update's save sees a stale version and must reload.
    repo.save(_article(title="v1"), expected_version=0)  # v1
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        if calls == 1:
            repo.save(_article(title="sneaky"), expected_version=1)  # concurrent writer -> v2
        return replace(article, title="updated")

    final = repo.update("01J0", mutate)
    assert calls == 2  # retried exactly once after the conflict
    assert final == 3  # sneaky (v2) then the retried update (v3)
    assert repo.load("01J0").article.title == "updated"


def test_update_reraises_conflict_after_exhausting_retries(repo: ArticleRepository) -> None:
    # A mutate whose every attempt loses to a concurrent writer must, after retries+1
    # attempts, re-raise Conflict rather than loop forever or silently give up.
    repo.save(_article(title="v1"), expected_version=0)  # v1
    calls = 0

    def mutate(article: Article) -> Article:
        nonlocal calls
        calls += 1
        # Always sneak a winning concurrent save first, so update's save is always stale.
        repo.save(_article(title=f"sneaky-{calls}"), expected_version=repo.load("01J0").version)
        return replace(article, title="never-lands")

    with pytest.raises(Conflict):
        repo.update("01J0", mutate, retries=1)
    assert calls == 2  # initial attempt + exactly one retry, then re-raise


class _RecordingStore(InMemoryObjectStore):
    """A real in-memory store that also records the order of write_atomic keys — a spy at the
    genuine ObjectStore boundary (not a mock of the repository), to pin write ordering."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def write_atomic(self, key: str, data: bytes) -> None:
        self.writes.append(key)
        super().write_atomic(key, data)


def test_save_writes_a_correct_append_only_change_record(repo: ArticleRepository) -> None:
    import json

    repo.save(_article(), expected_version=0)  # v1
    repo.save(_article(title="revised"), expected_version=1)  # v2
    record = json.loads(repo._store.read("articles/01J0/changes/1.json"))
    assert record == {"ulid": "01J0", "version": 1}
    assert repo._store.exists("articles/01J0/changes/2.json") is True


def test_save_writes_the_readme_commit_before_the_changes_record() -> None:
    # The pinned order is README (the commit) -> changes; a crash between them leaves a
    # durably-saved Article with only its change-log record missing (tolerable per ADR 0005).
    store = _RecordingStore()
    repo = ArticleRepository(store)
    repo.save(_article(), expected_version=0)
    assert store.writes.index("articles/01J0/README.md") < store.writes.index(
        "articles/01J0/changes/1.json"
    )


def test_racing_saves_one_winner_one_conflict_readme_at_winner_version(
    repo: ArticleRepository,
) -> None:
    """Two threads save the same Article at the same expected_version. The shared writer
    mutex (ADR 0013) serializes the check-then-write critical section, so EXACTLY one wins
    and the other sees a stale version -> Conflict. Assert the README version ends at the
    winner's version + 1 — NEVER against changes/*.json presence (gap-tolerant, ADR 0005).

    A barrier releases both threads together to force the interleave through the mutex; the
    mutex makes the outcome deterministic once both are past the barrier, so there are no
    sleeps and no flakiness.
    """
    repo.save(_article(), expected_version=0)  # store is now at v1
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    lock = threading.Lock()

    def attempt(name: str) -> None:
        barrier.wait()  # both threads arrive, then both race the save
        try:
            new_version = repo.save(_article(title=name), expected_version=1)
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
    # Assert the README version (the CAS source of truth), never changes/*.json presence.
    assert repo.load("01J0").version == 2
    raw = repo._store.read("articles/01J0/README.md").decode("utf-8")
    assert readme.read_version("01J0", raw) == 2
