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
from bundesarchiv.app.mirror import PushRecord, delete_article, push, reconcile
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
    or not), fetch or delete. It refuses every send from the ``fail_from``-th on, and every send
    of a key in ``refused``."""

    def __init__(self) -> None:
        self.store = InMemoryObjectStore()
        self.sent: list[str] = []
        self.fetched: list[str] = []
        self.deleted: list[str] = []
        self.fail_from: int | None = None
        self.refused: set[str] = set()

    def _sending(self, key: str) -> None:
        self.sent.append(key)
        if key in self.refused or (self.fail_from is not None and len(self.sent) >= self.fail_from):
            raise ArchiveError(f"{key}: the system of record refused it")

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


type _Sync = Callable[[Archive, _Remote, PushRecord], None]


def _by_push(archive: Archive, remote: _Remote, record: PushRecord) -> None:
    push(archive, remote, record, ULID)


def _by_reconcile(archive: Archive, remote: _Remote, record: PushRecord) -> None:
    if reconcile(archive, remote, record).failed:
        raise ArchiveError("the reconcile broke off")


_SYNCS = pytest.mark.parametrize("sync", [_by_push, _by_reconcile], ids=["push", "reconcile"])


@_SYNCS
@pytest.mark.parametrize("fail_from", range(1, 5))
def test_an_interrupted_push_never_leaves_a_readme_naming_a_file_the_system_of_record_lacks(
    sync: _Sync, fail_from: int
) -> None:
    """ADR 0020 push order, at every point a push of the second version can break off. The retry
    then completes it."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("eins.jpg", b"eins"))
    sync(archive, remote, record)
    _save(archive, ("zwei.jpg", b"zwei"), ("drei.pdf", b"drei"), title="Neu")
    remote.fail_from = len(remote.sent) + fail_from
    with pytest.raises(ArchiveError):
        sync(archive, remote, record)
    assert _dangling(remote.store) == []
    remote.fail_from = None
    sync(archive, remote, record)
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


def test_a_hard_delete_takes_exactly_its_folder_off_the_system_of_record_and_the_record() -> None:
    """``01FOTO2`` shares the folder's name as a string prefix and stays."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    archive.articles.save(Article("01FOTO2", "Nachbar", "FOTOS"), 0, changed_by="tester")
    reconcile(archive, remote, record)
    archive.articles.hard_delete(ULID)
    delete_article(archive, remote, record, ULID)
    assert _same_tree(archive, remote)
    assert record.entries().keys() == set(archive.store.list())


# --- the reconcile ---------------------------------------------------------------------


def _saved_collection(archive: Archive) -> None:
    archive.collections.save(Collection("FOTOS", "Fotos"), 0, changed_by="tester")


def test_a_lost_push_is_made_good_by_the_next_reconcile() -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _saved_collection(archive)
    _save(archive, ("scan.pdf", b"a scan"))
    reconcile(archive, remote, record)
    assert _same_tree(archive, remote)
    _save(archive, title="Neu")
    report = reconcile(archive, remote, record)
    _, history, readme = (key.key for key in archive.articles.keys_for(ULID))
    assert (report.sent, report.failed) == ((history, readme), ())
    assert _same_tree(archive, remote)


def test_a_record_whose_push_breaks_off_is_reported_and_the_sweep_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    archive, remote = Archive.of(InMemoryObjectStore()), _Remote()
    scan = archive.articles.add_media("01A", "scan.pdf", io.BytesIO(b"a scan"))
    archive.articles.save(Article("01A", "Eins", "FOTOS", media=(scan,)), 0, changed_by="tester")
    archive.articles.save(Article("01B", "Zwei", "FOTOS"), 0, changed_by="tester")
    remote.refused.add(archive.articles.media_key("01A", scan))
    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        report = reconcile(archive, remote, InMemoryPushRecord())
    assert report.failed == ("01A",)
    assert list(remote.store.list()) == [key.key for key in archive.articles.keys_for("01B")]
    assert "01A" in caplog.text


def test_a_file_the_system_of_record_lost_is_pushed_again_though_the_record_holds_it() -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    media, readme = (key.key for key in archive.articles.keys_for(ULID))
    remote.store.delete(media)
    remote.store.delete(readme)
    assert reconcile(archive, remote, record).sent == (media, readme)
    assert _same_tree(archive, remote)


def test_the_reconcile_deletes_nothing_and_reports_what_only_the_system_of_record_holds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A hard-deleted Article whose delete never reached the system of record stays there, and
    shows in the report (ADR 0020, accepted risk); so does a file that is not the app's."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    deleted = [key.key for key in archive.articles.keys_for(ULID)]
    archive.articles.hard_delete(ULID)
    remote.store.write_atomic("Notizen/liste.txt", b"not the app's")
    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        report = reconcile(archive, remote, record)
    assert report.remote_only == tuple(sorted([*deleted, "Notizen/liste.txt"]))
    assert remote.deleted == []
    assert set(remote.store.list()) == {*deleted, "Notizen/liste.txt"}
    assert "Notizen/liste.txt" in caplog.text


def test_a_hand_edit_on_the_system_of_record_is_reported_and_left_alone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    _, readme = (key.key for key in archive.articles.keys_for(ULID))
    remote.store.write_atomic(readme, b"edited by hand")
    sent = len(remote.sent)
    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        report = reconcile(archive, remote, record)
    assert (report.changed, report.sent) == ((readme,), ())
    assert (len(remote.sent), remote.store.read(readme)) == (sent, b"edited by hand")
    assert readme in caplog.text


def test_losing_the_push_record_costs_one_rebuild_and_no_upload() -> None:
    """The rebuild takes write-once files by their existence and each README by one download
    (ADR 0020); a second reconcile then moves no bytes at all."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _saved_collection(archive)
    _save(archive, ("eins.jpg", b"eins"), ("zwei.pdf", b"zwei"))
    _save(archive, title="Neu")
    reconcile(archive, remote, record)
    sent = len(remote.sent)
    rebuilt = InMemoryPushRecord()
    report = reconcile(archive, remote, rebuilt)
    readmes = sorted(key for key in archive.store.list() if key.endswith("/README.md"))
    assert (report.sent, report.changed, len(remote.sent)) == ((), (), sent)
    assert sorted(remote.fetched) == readmes
    assert rebuilt.entries() == record.entries()
    report = reconcile(archive, remote, rebuilt)
    assert (report.sent, report.recorded, len(remote.fetched)) == ((), (), len(readmes))


def test_a_readme_that_no_longer_decodes_is_never_pushed(caplog: pytest.LogCaptureFixture) -> None:
    """A README that rotted locally must not replace the intact copy on the system of record, by
    the per-save push or by the reconcile; the repository says which README does not decode."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    push(archive, remote, record, ULID)
    _, readme = (key.key for key in archive.articles.keys_for(ULID))
    intact, noted = remote.store.read(readme), record.entries()
    archive.store.write_atomic(readme, intact.replace(b"Foto", b"F\xf6to"))
    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        push(archive, remote, record, ULID)
        report = reconcile(archive, remote, record)
    assert report.unreadable == (readme,)
    assert (remote.store.read(readme), record.entries()) == (intact, noted)
    assert readme in caplog.text


def test_a_write_once_file_there_in_another_size_is_reported_and_neither_recorded_nor_replaced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """By the per-save push and by the reconcile: the system of record's file is not the local one,
    so the record must not vouch for it, and write-once means it stays."""
    archive, remote, record = Archive.of(InMemoryObjectStore()), _Remote(), InMemoryPushRecord()
    _save(archive, ("scan.pdf", b"a scan"))
    media, _ = (key.key for key in archive.articles.keys_for(ULID))
    remote.store.create(media, b"another file")
    with caplog.at_level("WARNING", logger="bundesarchiv.app.mirror"):
        push(archive, remote, record, ULID)
    assert (remote.store.read(media), media in record.entries()) == (b"another file", False)
    assert media in caplog.text
    report = reconcile(archive, remote, record)
    assert report.mismatched == (media,)
    assert (remote.store.read(media), media in record.entries()) == (b"another file", False)
