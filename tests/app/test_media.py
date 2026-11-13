"""Media intake (``app.media``): admission, one listed file per content hash, and the finish of a
chunked upload (ADR 0026)."""

import fcntl
import io
from dataclasses import replace
from pathlib import Path

import pytest

from bundesarchiv.app import media
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, Updated
from bundesarchiv.app.upload_staging import Key, Staging, Upload
from bundesarchiv.domain.models import ULID, Article, Collection, MediaRef
from bundesarchiv.index.refresh import InMemoryIndex
from bundesarchiv.persistence import readme
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

_ULID = ULID("01KX7YT9E3VX0CP3A5Q49RZMVH")
_ROOT = ULID("ROOT")
_DATA = b"%PDF-1.4 zwei Stuecke"


class _Concurrent(InMemoryObjectStore):
    """Another archivist writing around the reads of a README. While ``racing``, a save lands
    right after every read, so every save attempt finds the version it loaded gone. Once
    ``claimed``, an upload's bytes, is locked by a claim, the next read finds the Article moved to
    the Papierkorb just before."""

    racing = False
    claimed: Path | None = None

    def read(self, key: str) -> bytes:
        if key.endswith("/README.md") and self.claimed is not None and _locked(self.claimed):
            self.claimed = None
            repository = ArticleRepository(self)
            stored = repository.load(_ULID)
            repository.mark_deleted(stored.article, stored.version, changed_by="bert")
        data = super().read(key)
        if self.racing and key.endswith("/README.md"):
            article, version, change = readme.decode(_ULID, data.decode())
            assert change is not None
            self.write_atomic(key, readme.encode(article, version + 1, change).encode())
        return data


def _locked(data: Path) -> bool:
    with data.open("rb") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


@pytest.fixture
def store() -> _Concurrent:
    return _Concurrent()


@pytest.fixture
def archive(store: _Concurrent) -> Archive:
    """One Article holding one file, ``cover.jpg``."""
    archive = Archive.of(store, InMemoryIndex)
    archive.collections.save(Collection(_ROOT, "Wurzel", None), 0, changed_by="tester")
    cover = archive.articles.add_media(_ULID, "cover.jpg", io.BytesIO(b"cover"), "image/jpeg")
    archive.articles.save(
        Article(ulid=_ULID, title="Lagerchronik", collection_id=_ROOT, media=(cover,)),
        0,
        changed_by="tester",
    )
    return archive


def _incoming(name: str, data: bytes, media_type: str | None = None) -> media.Incoming:
    return media.Incoming(name, io.BytesIO(data), media_type)


def _media(archive: Archive) -> tuple[MediaRef, ...]:
    return archive.articles.load(_ULID).article.media


def _names(archive: Archive) -> list[str]:
    return [ref.filename for ref in _media(archive)]


def _changed_by(archive: Archive) -> str | None:
    change = archive.articles.load(_ULID).change
    return None if change is None else change.by


# --- admission ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "size", "refused"),
    [
        ("scan.pdf", 0, None),
        ("scan.pdf", 100, None),
        ("scan.pdf", 101, media.Refusal.TOO_LARGE),
        (" . ", 1, media.Refusal.NAMELESS),
        (" . ", 101, media.Refusal.NAMELESS),
    ],
)
def test_admission_refuses_a_nameless_or_oversize_file(
    filename: str, size: int, refused: media.Refusal | None
) -> None:
    assert media.refusal(filename, size, ceiling=100) is refused


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("application/pdf", "application/pdf"),
        ("image/svg+xml", "image/svg+xml"),
        (None, None),
        ("", None),
        ("pdf", None),
        ("application/pdf; charset=binary", None),
        ("text/html\r\nX-Evil: 1", None),
    ],
)
def test_a_media_type_is_kept_only_in_a_media_types_shape(
    archive: Archive, given: str | None, kept: str | None
) -> None:
    """It is served back as the file's Content-Type header, where a line break would break every
    answer."""
    media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA, given)], changed_by="anna")
    assert _media(archive)[-1].media_type == kept


# --- attach -----------------------------------------------------------------------------------


def test_attach_lists_new_files_in_posted_order_after_the_media(archive: Archive) -> None:
    outcome = media.attach(
        archive,
        _ULID,
        [_incoming("b.pdf", b"bbb"), _incoming("a.pdf", b"aaa")],
        changed_by="anna",
    )
    assert isinstance(outcome, Updated)
    assert _names(archive) == ["cover.jpg", "b.pdf", "a.pdf"]
    assert _changed_by(archive) == "anna"


def test_attach_lists_the_same_bytes_once_within_one_call(archive: Archive) -> None:
    media.attach(
        archive,
        _ULID,
        [_incoming("scan.pdf", _DATA), _incoming("kopie.pdf", _DATA)],
        changed_by="anna",
    )
    assert _names(archive) == ["cover.jpg", "scan.pdf"]


def test_attach_lists_bytes_the_article_holds_once(archive: Archive) -> None:
    media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA)], changed_by="anna")
    media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA)], changed_by="anna")
    media.attach(archive, _ULID, [_incoming("cover.jpg", b"cover")], changed_by="anna")
    assert _names(archive) == ["cover.jpg", "scan.pdf"]


def test_attaching_only_files_the_article_holds_writes_no_version(archive: Archive) -> None:
    media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA)], changed_by="anna")
    stored = archive.articles.load(_ULID)
    outcome = media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA)], changed_by="bert")
    assert isinstance(outcome, Updated) and outcome.version == stored.version
    assert archive.articles.load(_ULID) == stored


def test_attach_to_an_article_in_the_papierkorb_is_missing(archive: Archive) -> None:
    stored = archive.articles.load(_ULID)
    archive.articles.mark_deleted(stored.article, stored.version, changed_by="bert")
    outcome = media.attach(archive, _ULID, [_incoming("scan.pdf", _DATA)], changed_by="anna")
    assert outcome == Missing()


# --- finish_staged ------------------------------------------------------------------------------


@pytest.fixture
def staging(tmp_path: Path) -> Staging:
    return Staging(tmp_path)


def _staged(staging: Staging, data: bytes = _DATA, length: int | None = None) -> Key:
    upload = Upload(
        _ULID, "anna", "scan.pdf", "application/pdf", len(data) if length is None else length
    )
    key = Key(staging.create(upload), "anna", _ULID)
    assert staging.append(key, 0, io.BytesIO(data), len(data)) == len(data)
    return key


def test_a_finish_attaches_the_upload_and_frees_its_bytes(
    archive: Archive, staging: Staging, tmp_path: Path
) -> None:
    key = _staged(staging)
    outcome = media.finish_staged(archive, staging, key)
    assert isinstance(outcome, Updated)
    ref = _media(archive)[-1]
    assert (ref.filename, ref.media_type) == ("scan.pdf", "application/pdf")
    assert _changed_by(archive) == "anna"
    with archive.articles.open_media(_ULID, ref) as stored:
        assert stored.read() == _DATA
    assert (tmp_path / key.upload_id / "data").stat().st_size == 0


def test_a_repeated_finish_answers_the_stored_article_and_saves_nothing(
    archive: Archive, staging: Staging
) -> None:
    key = _staged(staging)
    media.finish_staged(archive, staging, key)
    stored = archive.articles.load(_ULID)
    keys = archive.articles.keys_for(_ULID)

    assert media.finish_staged(archive, staging, key) == media.Repeated(stored)
    assert archive.articles.keys_for(_ULID) == keys


def test_a_finish_of_an_incomplete_upload_is_none_and_keeps_its_bytes(
    archive: Archive, staging: Staging
) -> None:
    key = _staged(staging, _DATA[:8], length=len(_DATA))
    keys = archive.articles.keys_for(_ULID)
    assert media.finish_staged(archive, staging, key) is None
    assert archive.articles.keys_for(_ULID) == keys
    assert (staged := staging.status(key)) is not None and staged[1] == 8


def test_a_finish_that_loses_every_save_race_keeps_the_upload_for_the_next(
    archive: Archive, staging: Staging, store: _Concurrent
) -> None:
    key = _staged(staging)
    store.racing = True
    assert media.finish_staged(archive, staging, key) == Conflicted()
    store.racing = False
    assert _names(archive) == ["cover.jpg"]

    assert isinstance(media.finish_staged(archive, staging, key), Updated)
    assert _names(archive) == ["cover.jpg", "scan.pdf"]


def test_a_finish_whose_article_goes_to_the_papierkorb_while_it_waits_keeps_the_upload(
    archive: Archive, staging: Staging, store: _Concurrent, tmp_path: Path
) -> None:
    key = _staged(staging)
    store.claimed = tmp_path / key.upload_id / "data"
    assert media.finish_staged(archive, staging, key) == Missing()
    deleted = archive.articles.load(_ULID)
    archive.articles.save(
        replace(deleted.article, deleted=None), deleted.version, changed_by="bert"
    )

    assert isinstance(media.finish_staged(archive, staging, key), Updated)
    assert _names(archive) == ["cover.jpg", "scan.pdf"]


def test_a_repeated_finish_loads_the_article_once_it_holds_the_upload(
    archive: Archive, staging: Staging, store: _Concurrent, tmp_path: Path
) -> None:
    """A repeat that waited on the upload sees every write that landed meanwhile."""
    key = _staged(staging)
    media.finish_staged(archive, staging, key)
    store.claimed = tmp_path / key.upload_id / "data"
    assert media.finish_staged(archive, staging, key) == Missing()
