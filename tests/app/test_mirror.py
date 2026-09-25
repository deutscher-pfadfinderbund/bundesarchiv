"""The push to the system of record (ADR 0020), the mirror logic over two in-memory stores: the
working copy an ``Archive`` holds, and ``_Remote`` standing in for the Nextcloud folder, which logs
every call that sends, fetches or deletes bytes. The push record is the in-memory fake; its
Postgres twin answers the same contract (``test_push_record.py``)."""

import io
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import BinaryIO

import pytest

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.mirror import ReconcileSummary, push, reconcile
from bundesarchiv.app.push_record import InMemoryPushRecord
from bundesarchiv.domain.models import Article, Collection
from bundesarchiv.persistence._writer import history_key
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import ObjectEntry, ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

ULID = "01FOTO"


class _Remote:
    """The system of record: an in-memory store that logs each key it is asked to send (refused
    or not), fetch or delete, and refuses every send from the ``fail_from``-th on."""

    def __init__(self) -> None:
        self.store = InMemoryObjectStore()
        self.sent: list[str] = []
        self.fetched: list[str] = []
        self.deleted: list[str] = []
        self.fail_from: int | None = None

    def _sending(self, key: str) -> None:
        self.sent.append(key)
        if self.fail_from is not None and len(self.sent) >= self.fail_from:
            raise ArchiveError(f"{key}: the system of record is unreachable")

    def read(self, key: str) -> bytes:
        self.fetched.append(key)
        return self.store.read(key)

    def open_stream(self, key: str) -> BinaryIO:
        self.fetched.append(key)
        return self.store.open_stream(key)

    def write_atomic(self, key: str, data: bytes) -> str:
        self._sending(key)
        return self.store.write_atomic(key, data)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> str:
        self._sending(key)
        return self.store.put_large(key, stream, size)

    def create(self, key: str, data: bytes) -> str:
        self._sending(key)
        return self.store.create(key, data)

    def create_large(self, key: str, stream: BinaryIO, size: int) -> str:
        self._sending(key)
        return self.store.create_large(key, stream, size)

    def list(self, prefix: str = "") -> Iterable[str]:
        return self.store.list(prefix)

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        return self.store.list_entries(prefix)

    def exists(self, key: str) -> bool:
        return self.store.exists(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.store.delete(key)

    def delete_prefix(self, prefix: str) -> None:
        self.deleted.append(prefix)
        self.store.delete_prefix(prefix)


def _save(archive: Archive, *uploads: tuple[str, bytes], title: str = "Foto") -> None:
    """Save the Article ``ULID`` as its next version, with ``uploads`` added to its media."""
    articles = archive.articles
    try:
        stored = articles.load(ULID)
        article, version = stored.article, stored.version
    except NotFound:
        article, version = Article(ULID, title, "FOTOS"), 0
    added = tuple(articles.add_media(ULID, name, io.BytesIO(data)) for name, data in uploads)
    article = replace(article, title=title, media=(*article.media, *added))
    articles.save(article, version, changed_by="tester")


def _dangling(store: ObjectStore) -> list[str]:
    """The files the README in ``store`` stands on, its media and its older versions, that
    ``store`` lacks."""
    repo = ArticleRepository(store)
    try:
        stored = repo.load(ULID)
    except NotFound:
        return []
    named = [repo.media_key(ULID, ref) for ref in stored.article.media]
    named += [history_key(f"articles/{ULID}", version) for version in range(1, stored.version)]
    return [key for key in named if not store.exists(key)]


def _same_tree(archive: Archive, remote: _Remote) -> bool:
    local = {key: archive.store.read(key) for key in archive.store.list()}
    return local == {key: remote.store.read(key) for key in remote.store.list()}


# --- the per-save push -------------------------------------------------------------


@pytest.mark.parametrize("fail_from", range(1, 5))
def test_an_interrupted_push_never_leaves_a_readme_naming_a_file_the_system_of_record_lacks(
    fail_from: int,
) -> None:
    """ADR 0020 push order, at every point a push of the second version can break off. The retry
    then completes it."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("eins.jpg", b"eins"))
    push(archive, remote, record, ULID)
    _save(archive, ("zwei.jpg", b"zwei"), ("drei.pdf", b"drei"), title="Neu")
    remote.fail_from = len(remote.sent) + fail_from
    with pytest.raises(ArchiveError):
        push(archive, remote, record, ULID)
    assert _dangling(remote.store) == []
    remote.fail_from = None
    push(archive, remote, record, ULID)
    assert _same_tree(archive, remote)


class _SavedAfterTheFirstListing(InMemoryObjectStore):
    """A working copy on which a save lands right after the first listing that finds files."""

    def __init__(self) -> None:
        super().__init__()
        self.then: list[Callable[[], None]] = []

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        listed = super().list_entries(prefix)
        if listed and self.then:
            self.then.pop()()
        return listed


def test_a_save_landing_while_the_push_lists_the_article_never_reaches_it_half() -> None:
    """The README the push sends is read before the listing it sends the files from."""
    working = _SavedAfterTheFirstListing()
    archive, remote = Archive.of(working), _Remote()
    _save(archive, ("eins.jpg", b"eins"))
    working.then.append(lambda: _save(archive, ("zwei.jpg", b"zwei"), title="Neu"))
    push(archive, remote, InMemoryPushRecord(), ULID)
    assert _dangling(remote.store) == []
    assert _same_tree(archive, remote)


def test_an_unchanged_file_is_never_sent_twice() -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    _save(archive, title="Neue Bildunterschrift")
    push(archive, remote, record, ULID)
    push(archive, remote, record, ULID)
    media, history, readme = (key.key for key in archive.articles.keys_for(ULID))
    assert remote.sent == [media, readme, history, readme]


def _collection_saved(archive: Archive, name: str) -> None:
    try:
        version = archive.collections.load(ULID).version
    except NotFound:
        version = 0
    archive.collections.save(Collection(ULID, name), version, changed_by="tester")


@pytest.mark.parametrize(
    "save",
    [lambda archive, name: _save(archive, title=name), _collection_saved],
    ids=["article", "collection"],
)
def test_a_changed_readme_is_pushed(save: Callable[[Archive, str], None]) -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    save(archive, "eins")
    push(archive, remote, record, ULID)
    save(archive, "zwei")
    push(archive, remote, record, ULID)
    assert _same_tree(archive, remote)


def test_a_write_once_file_already_there_is_recorded_not_sent_again() -> None:
    """A lost push record costs no upload of a file the system of record already holds (a create
    sends the whole body before it learns the key is taken)."""
    archive, remote = Archive.of(InMemoryObjectStore()), _Remote()
    _save(archive, ("video.mp4", b"a long film"))
    push(archive, remote, InMemoryPushRecord(), ULID)
    _save(archive, title="Neu")
    before = len(remote.sent)
    push(archive, remote, InMemoryPushRecord(), ULID)
    _, history, readme = (key.key for key in archive.articles.keys_for(ULID))
    assert remote.sent[before:] == [history, readme]
    assert _same_tree(archive, remote)


def test_the_push_of_a_hard_deleted_article_deletes_nothing() -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    pushed = list(remote.store.list())
    archive.articles.hard_delete(ULID)
    push(archive, remote, record, ULID)
    assert (remote.deleted, list(remote.store.list())) == ([], pushed)


def _stores() -> tuple[InMemoryObjectStore, InMemoryObjectStore]:
    return InMemoryObjectStore(), InMemoryObjectStore()


# --- reconcile: full diff, push missing/changed, delete mirror-only --------------


def test_reconcile_pushes_missing_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    canonical.write_atomic("articles/01B/README.md", b"b")

    summary = reconcile(canonical, mirror)

    assert mirror.read("articles/01A/README.md") == b"a"
    assert mirror.read("articles/01B/README.md") == b"b"
    assert summary.pushed == 2
    assert summary.deleted == 0
    assert summary.failed == 0


def test_reconcile_repushes_changed_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"fresh")
    mirror.write_atomic("articles/01A/README.md", b"stale")  # same key, different bytes

    summary = reconcile(canonical, mirror)

    assert mirror.read("articles/01A/README.md") == b"fresh"
    assert summary.pushed == 1  # changed key counts as a push


def test_reconcile_skips_unchanged_keys() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"same")
    mirror.write_atomic("articles/01A/README.md", b"same")

    summary = reconcile(canonical, mirror)

    assert summary.pushed == 0  # identical bytes: nothing re-pushed
    assert summary.deleted == 0


def test_reconcile_deletes_mirror_only_keys() -> None:
    """The mirror MIRRORS — it does not accumulate. A key present on the mirror but absent from
    canonical is stale and must be deleted."""
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"keep")
    mirror.write_atomic("articles/01A/README.md", b"keep")
    mirror.write_atomic("articles/01OLD/README.md", b"deleted-from-canonical")

    summary = reconcile(canonical, mirror)

    assert not mirror.exists("articles/01OLD/README.md")  # stale mirror-only key removed
    assert mirror.exists("articles/01A/README.md")  # still-canonical key kept
    assert summary.deleted == 1


def test_reconcile_empty_canonical_clears_mirror() -> None:
    canonical, mirror = _stores()
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")

    summary = reconcile(canonical, mirror)

    assert list(mirror.list()) == []
    assert summary.deleted == 1
    assert summary.pushed == 0


def test_reconcile_summary_is_the_result_shape() -> None:
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")

    summary = reconcile(canonical, mirror)

    assert isinstance(summary, ReconcileSummary)
    assert (summary.pushed, summary.deleted, summary.failed) == (1, 1, 0)


# --- mass-delete warning: a misconfigured mirror root must be an actionable signal


def test_reconcile_mass_delete_logs_warning_with_sample_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sweep that deletes an anomalous number of mirror-only keys (the signature of
    BUNDESARCHIV_MIRROR_DAV_URL pointed at a folder holding non-archive files) must log a WARNING
    naming the count and a bounded sample of the deleted keys — an actionable signal, not a silent
    count in the summary."""
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    for i in range(30):  # 30 > the absolute threshold of 25
        mirror.write_atomic(f"human-files/photo-{i:02}.jpg", b"not-archive-content")

    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        summary = reconcile(canonical, mirror)

    assert summary.deleted == 30
    warning = "\n".join(r.message for r in caplog.records if r.levelname == "WARNING")
    assert "30" in warning  # the count
    assert "human-files/photo-00.jpg" in warning  # a sample of WHAT was deleted
    assert warning.count("human-files/") <= 20  # the sample is bounded, not the full list


def test_reconcile_small_delete_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    """Routine mirror deletes (e.g. a hard-deleted Article's few keys) stay below the threshold —
    no warning noise for normal operation."""
    canonical, mirror = _stores()
    canonical.write_atomic("articles/01A/README.md", b"a")
    mirror.write_atomic("articles/01OLD/README.md", b"orphan")

    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        reconcile(canonical, mirror)

    assert not [r for r in caplog.records if r.levelname == "WARNING"]
