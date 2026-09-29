"""ArticleRepository behaviour, exercised through its interface over both the
in-memory ObjectStore fake and the LocalFs adapter (the Collection conformance
pattern) — the canonical-file protocol, optimistic concurrency, named write-once media
(ADR 0019), and the hard delete (ADR 0020).
"""

import io
import threading
from collections.abc import Iterable
from pathlib import Path

import pytest

from bundesarchiv.domain.models import Article, Audience, AudienceTier, Lifecycle, MediaRef
from bundesarchiv.persistence import readme
from bundesarchiv.persistence._writer import history_key, readme_key
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError, Conflict, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository, cleaned_name


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


def test_list_ulids_returns_articles_not_media_or_history(repo: ArticleRepository) -> None:
    repo.save(_article("01A"), expected_version=0, changed_by="tester")
    repo.save(_article("01A", title="revised"), expected_version=1, changed_by="tester")
    repo.save(_article("01B"), expected_version=0, changed_by="tester")
    assert set(repo.list_ulids()) == {"01A", "01B"}


def _stored_name(repo: ArticleRepository, ulid: str, ref: MediaRef) -> str:
    return repo.media_key(ulid, ref).rsplit("/", 1)[1]


def test_a_file_is_stored_under_the_name_it_was_uploaded_with(repo: ArticleRepository) -> None:
    ref = repo.add_media(
        "01J0", "Brief 1956.pdf", io.BytesIO(b"the bytes"), media_type="application/pdf"
    )
    assert (ref.filename, ref.stored_name, ref.byte_size) == ("Brief 1956.pdf", None, 9)
    assert [key.key for key in repo.keys_for("01J0")] == [repo.media_key("01J0", ref)]
    assert repo._store.read(repo.media_key("01J0", ref)) == b"the bytes"


def test_the_same_name_with_the_same_bytes_reuses_the_file(repo: ArticleRepository) -> None:
    first = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    again = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    assert again == first
    assert [key.key for key in repo.keys_for("01J0")] == [repo.media_key("01J0", first)]


def test_the_same_name_with_other_bytes_keeps_both_files(repo: ArticleRepository) -> None:
    first = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"first scan"))
    # the same size: only the hash tells the two apart
    second = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"later scan"))
    assert repo._store.read(repo.media_key("01J0", first)) == b"first scan"
    assert repo._store.read(repo.media_key("01J0", second)) == b"later scan"
    assert second.filename == "scan.pdf"
    assert second.stored_name is not None
    stem, suffix, ext = second.stored_name.split(".")
    assert (stem, suffix, ext) == ("scan", second.content_hash[:8], "pdf")


def test_a_taken_hash_suffix_falls_back_to_the_full_hash(repo: ArticleRepository) -> None:
    replaced = b"replaced scan"
    short = repo.add_media("PROBE", "x", io.BytesIO(replaced)).content_hash[:8]
    repo.add_media("01J0", "scan.pdf", io.BytesIO(b"first scan"))
    repo.add_media(
        "01J0", f"scan.{short}.pdf", io.BytesIO(b"a file that happens to carry that name")
    )
    ref = repo.add_media("01J0", "scan.pdf", io.BytesIO(replaced))
    assert ref.stored_name == f"scan.{ref.content_hash}.pdf"
    assert repo._store.read(repo.media_key("01J0", ref)) == replaced


def test_re_uploading_a_replaced_scan_reuses_its_suffixed_file(repo: ArticleRepository) -> None:
    repo.add_media("01J0", "scan.pdf", io.BytesIO(b"first scan"))
    second = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"replaced scan"))
    assert repo.add_media("01J0", "scan.pdf", io.BytesIO(b"replaced scan")) == second
    assert len(repo.keys_for("01J0")) == 2


class _ListedBeforeTheRace(InMemoryObjectStore):
    """Every listing was taken before a concurrent upload's create landed."""

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        return []


def test_an_upload_that_loses_the_create_race_keeps_both_files() -> None:
    repo = ArticleRepository(_ListedBeforeTheRace())
    first = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"first scan"))
    second = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"later scan"))
    assert repo._store.read(repo.media_key("01J0", first)) == b"first scan"
    assert repo._store.read(repo.media_key("01J0", second)) == b"later scan"
    assert repo.add_media("01J0", "scan.pdf", io.BytesIO(b"first scan")) == first


@pytest.mark.parametrize(
    ("taken", "upload"),
    [("Scan.pdf", "scan.pdf"), ("scan.pdf", "SCAN.PDF"), ("Straße.pdf", "STRASSE.pdf")],
)
def test_names_that_differ_only_in_case_collide(
    repo: ArticleRepository, taken: str, upload: str
) -> None:
    first = repo.add_media("01J0", taken, io.BytesIO(b"first"))
    reused = repo.add_media("01J0", upload, io.BytesIO(b"first"))
    other = repo.add_media("01J0", upload, io.BytesIO(b"other bytes"))
    assert _stored_name(repo, "01J0", reused) == taken
    assert reused.stored_name == taken  # recorded, because it differs from the uploaded name
    assert repo.media_key("01J0", other) != repo.media_key("01J0", first)
    assert len(repo.keys_for("01J0")) == 2


def test_names_that_differ_only_in_unicode_form_collide(repo: ArticleRepository) -> None:
    nfd, nfc = "Mu\u0308ller.pdf", "M\u00fcller.pdf"
    first = repo.add_media("01J0", nfd, io.BytesIO(b"first"))
    assert first.stored_name == nfc  # the stored name is NFC, so it differs from the upload
    second = repo.add_media("01J0", nfc, io.BytesIO(b"other bytes"))
    assert second.stored_name is not None
    assert len(repo.keys_for("01J0")) == 2


def test_a_name_on_the_disk_in_another_unicode_form_is_taken(repo: ArticleRepository) -> None:
    by_hand = repo.media_key("01J0", MediaRef("Mu\u0308ller.pdf", "0" * 64))
    repo._store.create(by_hand, b"placed by hand")
    ref = repo.add_media("01J0", "M\u00fcller.pdf", io.BytesIO(b"uploaded"))
    assert ref.stored_name is not None
    assert repo._store.read(repo.media_key("01J0", ref)) == b"uploaded"


@pytest.mark.parametrize(
    ("filename", "cleaned"),
    [
        ("scan.pdf", "scan.pdf"),
        ('a/b\\c:d*e?f"g<h>i|j.pdf', "a_b_c_d_e_f_g_h_i_j.pdf"),
        ("tab\there\x7fnul\x00c1\x85.pdf", "tab_here_nul_c1_.pdf"),
        ("  . .scan.pdf. . ", "scan.pdf"),
        ("Bericht .pdf", "Bericht .pdf"),
        ("Scan ..pdf", "Scan ..pdf"),
        ("Mu\u0308ller.pdf", "M\u00fcller.pdf"),
        ("100% M\u00fcller  #2.pdf", "100% M\u00fcller  #2.pdf"),
        ("_", "_"),
        ("...", None),
        ("   ", None),
        (" . . ", None),
        ("", None),
    ],
)
def test_the_cleaning_rule(filename: str, cleaned: str | None) -> None:
    assert cleaned_name(filename) == cleaned


@pytest.mark.parametrize(
    "filename",
    [
        "a" * 300 + ".pdf",
        "\u00fc" * 200 + ".pdf",
        "\u20ac" * 100 + ".tar.gz",
        "a" * 245 + " " + "b" * 10 + ".pdf",
        "\U0001f4f7" * 70 + ".jpeg",
    ],
)
def test_a_long_name_is_cut_to_250_bytes_and_keeps_its_extension(
    repo: ArticleRepository, filename: str
) -> None:
    ext = filename.rsplit(".", 1)[1]
    refs = [
        repo.add_media("01J0", filename, io.BytesIO(data)) for data in (b"one", b"two", b"three")
    ]
    names = [_stored_name(repo, "01J0", ref) for ref in refs]
    for name in names:
        assert len(name.encode()) <= 250
        assert name.endswith(f".{ext}")
        assert not name.removesuffix(f".{ext}").endswith((" ", "."))
    assert len(set(names)) == 3
    assert names[0] == cleaned_name(filename)


def test_an_extension_that_leaves_no_room_counts_as_part_of_the_name(
    repo: ArticleRepository,
) -> None:
    filename = "a." + "b" * 300
    refs = [repo.add_media("01J0", filename, io.BytesIO(data)) for data in (b"one", b"two")]
    names = [_stored_name(repo, "01J0", ref) for ref in refs]
    assert all(len(name.encode()) <= 250 and name.startswith("a.bbb") for name in names)
    assert names[0] != names[1]


def test_a_name_that_cleans_to_nothing_is_refused_and_nothing_is_written(
    repo: ArticleRepository,
) -> None:
    with pytest.raises(ValueError, match="nothing"):
        repo.add_media("01J0", " . . ", io.BytesIO(b"the bytes"))
    assert repo._store.list() == []


def test_media_key_is_the_declared_layout(repo: ArticleRepository) -> None:
    ref = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    assert repo.media_key("01J0", ref) == "articles/01J0/media/photo.jpg"


def test_keys_for_lists_the_files_in_the_order_a_save_writes_them(
    repo: ArticleRepository,
) -> None:
    """Only the README, written last, is replaced by a save (ADR 0020 push order). A media file
    carries its hash when the current README names it."""
    kept = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"kept scan"))
    dropped = repo.add_media("01J0", "alt.pdf", io.BytesIO(b"dropped scan"))
    repo.save(_article(media=(kept, dropped)), expected_version=0, changed_by="tester")
    repo.save(_article(media=(kept,)), expected_version=1, changed_by="tester")
    listed = [(key.key, key.write_once, key.sha256) for key in repo.keys_for("01J0")]
    assert listed == [
        (repo.media_key("01J0", dropped), True, None),
        (repo.media_key("01J0", kept), True, kept.content_hash),
        (history_key("articles/01J0", 1), True, None),
        (readme_key("articles/01J0"), False, None),
    ]
    assert [key.size for key in repo.keys_for("01J0")][:2] == [
        len(b"dropped scan"),
        len(b"kept scan"),
    ]


@pytest.mark.parametrize("rotten", [b"no front matter", b"---\ntitle: F\xf6to\n---\n"])
def test_keys_for_marks_a_readme_that_does_not_decode(
    repo: ArticleRepository, rotten: bytes
) -> None:
    """Such a README is never pushed over the intact copy on the system of record (ADR 0020)."""
    ref = repo.add_media("01J0", "scan.pdf", io.BytesIO(b"the bytes"))
    repo.save(_article(media=(ref,)), expected_version=0, changed_by="tester")
    assert all(key.readable for key in repo.keys_for("01J0"))
    repo._store.write_atomic(readme_key("articles/01J0"), rotten)
    listed = [(key.key, key.sha256, key.readable) for key in repo.keys_for("01J0")]
    assert listed == [
        (repo.media_key("01J0", ref), None, True),
        (readme_key("articles/01J0"), None, False),
    ]


def test_open_media_streams_the_file_and_absence_is_not_found(repo: ArticleRepository) -> None:
    ref = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    with repo.open_media("01J0", ref) as stream:
        assert stream.read() == b"the bytes"
    with pytest.raises(NotFound):
        repo.open_media("01J0", MediaRef("ghost.jpg", "0" * 64))


def test_add_media_carries_the_optional_caption(repo: ArticleRepository) -> None:
    # ADR 0015: add_media threads an optional caption into the returned ref; absent -> None.
    with_caption = repo.add_media(
        "01J0", "seite-a.mp3", io.BytesIO(b"audio"), caption="Seite A — Bericht"
    )
    assert with_caption.caption == "Seite A — Bericht"
    without = repo.add_media("01J0", "huelle.jpg", io.BytesIO(b"scan"))
    assert without.caption is None


def test_save_refuses_readme_referencing_unstored_media(repo: ArticleRepository) -> None:
    # The pinned order is media -> README. Referencing media that was never stored must fail,
    # writing nothing (no history file either), rather than commit a README that points at nothing.
    ref = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    repo.save(_article(media=(ref,)), expected_version=0, changed_by="tester")
    orphan = type(ref)(filename="ghost.jpg", content_hash="0" * 64)
    before = {key: repo._store.read(key) for key in repo._store.list()}
    with pytest.raises(ArchiveError):
        repo.save(_article(media=(ref, orphan)), expected_version=1, changed_by="tester")
    assert {key: repo._store.read(key) for key in repo._store.list()} == before


def test_a_hard_delete_leaves_nothing_of_the_article_on_disk(tmp_path: Path) -> None:
    """ADR 0020: final for the app, so no copy is kept, reserved or not. ``01J0X`` shares the
    folder's name as a string prefix and stays."""
    repo = ArticleRepository(LocalFsObjectStore(tmp_path))
    ref = repo.add_media("01J0", "photo.jpg", io.BytesIO(b"the bytes"))
    repo.save(_article(media=(ref,)), expected_version=0, changed_by="tester")
    repo.save(_article(media=(ref,), title="revised"), expected_version=1, changed_by="tester")
    repo.save(_article("01J0X"), expected_version=0, changed_by="tester")
    kept = {path: data for path, data in _files(tmp_path).items() if "01J0X" in path.parts}

    repo.hard_delete("01J0")

    assert _files(tmp_path) == kept


def _files(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_hard_delete_is_a_no_op_for_absent_article(repo: ArticleRepository) -> None:
    repo.hard_delete("never-existed")  # must not raise


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
