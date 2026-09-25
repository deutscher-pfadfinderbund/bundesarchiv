"""ArticleRepository behaviour, exercised through its interface over both the
in-memory ObjectStore fake and the LocalFs adapter (the Collection conformance
pattern) — the canonical-file protocol, optimistic concurrency, content-addressed
write-once media, and recoverable hard_delete.
"""

import threading
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
    version = repo.save(article, expected_version=0, changed_by="tester")
    assert version == 1
    loaded = repo.load("01J0")
    assert loaded.article == article  # every field, incl. German body with a --- rule
    assert loaded.version == 1


def test_load_missing_raises_not_found(repo: ArticleRepository) -> None:
    with pytest.raises(NotFound):
        repo.load("nope")


def test_stale_expected_version_raises_conflict(repo: ArticleRepository) -> None:
    repo.save(_article(), expected_version=0, changed_by="tester")  # -> v1
    with pytest.raises(Conflict):
        repo.save(
            _article(title="rename"), expected_version=0, changed_by="tester"
        )  # stale; store is at v1
    assert (
        repo.save(_article(title="rename"), expected_version=1, changed_by="tester") == 2
    )  # correct version wins


def test_readme_carries_marker_and_is_the_commit_point(repo: ArticleRepository) -> None:
    repo.save(_article(), expected_version=0, changed_by="tester")
    raw = repo._store.read("articles/01J0/README.md").decode("utf-8")
    assert raw.startswith("<!-- Managed by bundesarchiv")
    assert "Zeltlager 1955" in raw


def test_list_ulids_returns_articles_not_media_or_history(repo: ArticleRepository) -> None:
    repo.save(_article("01A"), expected_version=0, changed_by="tester")
    repo.save(_article("01A", title="revised"), expected_version=1, changed_by="tester")
    repo.save(_article("01B"), expected_version=0, changed_by="tester")
    assert set(repo.list_ulids()) == {"01A", "01B"}


def test_add_media_is_content_addressed_and_write_once(repo: ArticleRepository) -> None:
    first = repo.add_media("01J0", "photo.jpg", b"the bytes", media_type="image/jpeg")
    again = repo.add_media("01J0", "renamed.jpg", b"the bytes")  # same bytes
    assert first.content_hash == again.content_hash  # content-addressed
    assert first.byte_size == len(b"the bytes")
    # write-once: one blob under the Article, keyed by the hash
    assert set(repo.keys_for("01J0")) == {repo.media_key("01J0", first.content_hash)}


def test_add_media_carries_the_optional_caption(repo: ArticleRepository) -> None:
    # ADR 0015: add_media threads an optional caption into the returned ref; absent -> None.
    with_caption = repo.add_media("01J0", "seite-a.mp3", b"audio", caption="Seite A — Bericht")
    assert with_caption.caption == "Seite A — Bericht"
    without = repo.add_media("01J0", "huelle.jpg", b"scan")
    assert without.caption is None


def test_media_key_is_the_declared_blob_layout(repo: ArticleRepository) -> None:
    # THE one home of `articles/<ulid>/media/<hash>`: this literal is written down here and
    # nowhere else in src/ or tests/, so a layout change is a one-line change plus this red.
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    assert repo.media_key("01J0", ref.content_hash) == f"articles/01J0/media/{ref.content_hash}"
    assert repo._store.exists(repo.media_key("01J0", ref.content_hash))


def test_open_media_streams_the_blob_and_absence_is_not_found(repo: ArticleRepository) -> None:
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    with repo.open_media("01J0", ref.content_hash) as stream:
        assert stream.read() == b"the bytes"
    with pytest.raises(NotFound):
        repo.open_media("01J0", "0" * 64)


def test_find_blob_locates_the_bytes_under_any_article(repo: ArticleRepository) -> None:
    # Content-addressed + write-once: the same bytes may hang off several Articles and every
    # match is identical, so a hash alone names the bytes (the thumbnail job's whole need).
    ref = repo.add_media("01J9", "photo.jpg", b"the bytes")
    repo.add_media("01JA", "kopie.jpg", b"the bytes")
    assert repo.find_blob(ref.content_hash) == b"the bytes"


def test_find_blob_is_none_when_no_article_holds_the_hash(repo: ArticleRepository) -> None:
    repo.add_media("01J0", "photo.jpg", b"the bytes")
    assert repo.find_blob("0" * 64) is None


def test_find_blob_ignores_a_non_media_key_ending_in_the_hash(repo: ArticleRepository) -> None:
    # A history file or README whose name happens to end in the hash is not a blob — the
    # lookup matches the media segment, not a bare suffix.
    repo._store.write_atomic("articles/01J0/history/deadbeef", b"not a blob")
    assert repo.find_blob("deadbeef") is None


def test_save_refuses_readme_referencing_unstored_media(repo: ArticleRepository) -> None:
    # The pinned order is media -> README. Referencing media that was never stored must fail,
    # writing nothing (no history file either), rather than commit a README that points at nothing.
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    repo.save(_article(media=(ref,)), expected_version=0, changed_by="tester")
    orphan = type(ref)(filename="ghost.jpg", content_hash="0" * 64)
    before = {key: repo._store.read(key) for key in repo._store.list()}
    with pytest.raises(ArchiveError):
        repo.save(_article(media=(ref, orphan)), expected_version=1, changed_by="tester")
    assert {key: repo._store.read(key) for key in repo._store.list()} == before


def test_hard_delete_removes_article_but_keeps_recoverable_copy(repo: ArticleRepository) -> None:
    ref = repo.add_media("01J0", "photo.jpg", b"the bytes")
    repo.save(_article(media=(ref,)), expected_version=0, changed_by="tester")
    repo.save(_article(media=(ref,), title="revised"), expected_version=1, changed_by="tester")
    original = set(repo._store.list("articles/01J0/"))
    assert len(original) == 3  # README + the media blob + the v1 history file

    repo.hard_delete("01J0")

    with pytest.raises(NotFound):
        repo.load("01J0")
    assert list(repo.list_ulids()) == []  # gone from listings
    # recoverable: the ENTIRE subtree (README, media, history) lives under reserved .trash,
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


def test_racing_saves_one_winner_one_conflict_readme_at_winner_version(
    repo: ArticleRepository,
) -> None:
    """Two threads save the same Article at the same expected_version. The shared writer
    mutex (ADR 0013) serializes the check-then-write critical section, so EXACTLY one wins
    and the other sees a stale version -> Conflict. Assert the README version ends at the
    winner's version + 1.

    A barrier releases both threads together to force the interleave through the mutex; the
    mutex makes the outcome deterministic once both are past the barrier, so there are no
    sleeps and no flakiness.
    """
    repo.save(_article(), expected_version=0, changed_by="tester")  # store is now at v1
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    lock = threading.Lock()

    def attempt(name: str) -> None:
        barrier.wait()  # both threads arrive, then both race the save
        try:
            new_version = repo.save(_article(title=name), expected_version=1, changed_by="tester")
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
    raw = repo._store.read("articles/01J0/README.md").decode("utf-8")
    assert readme.read_version("01J0", raw) == 2
