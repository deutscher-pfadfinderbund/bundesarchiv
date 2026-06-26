"""ArticleRepository behaviour, exercised through its interface over the in-memory
ObjectStore fake (no disk) — the canonical-file protocol, optimistic concurrency,
content-addressed write-once media, and recoverable hard_delete.
"""

import pytest

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.repository import ArticleRepository


@pytest.fixture
def repo() -> ArticleRepository:
    return ArticleRepository(InMemoryObjectStore())


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

    repo.hard_delete("01J0")

    with pytest.raises(NotFound):
        repo.load("01J0")
    assert list(repo.list_ulids()) == []  # gone from listings
    # recoverable: the files live under reserved .trash, excluded from list()
    assert repo._store.exists(".trash/articles/01J0/README.md") is True
    assert set(repo._store.list()) == set()


def test_hard_delete_is_a_no_op_for_absent_article(repo: ArticleRepository) -> None:
    repo.hard_delete("never-existed")  # must not raise


def test_load_of_a_corrupt_readme_surfaces_archive_error(repo: ArticleRepository) -> None:
    # Integration: a damaged README must reach the caller as ArchiveError (the codec's
    # detailed corrupt-input cases are covered directly in test_readme.py).
    repo._store.write_atomic("articles/bad/README.md", b"---\ntags: [unclosed\n---\nbody")
    with pytest.raises(ArchiveError):
        repo.load("bad")
