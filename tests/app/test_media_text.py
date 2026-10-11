"""The page text: which files text is read from, what a file's bytes give, and the fill — each PDF
of an Article's current media is read once, a file that gives no text is not read again, bytes that
do not match their hash store nothing, and one bad file never stops the others."""

import io
from pathlib import Path
from typing import BinaryIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from tests._articles import make_article
from tests._pdfs import text_pdf

from bundesarchiv.app import media_text
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.media_text import HashMismatch, Pages, Unreadable
from bundesarchiv.domain.models import MediaRef
from bundesarchiv.index.models import MediaText
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.adapters.memory import InMemoryObjectStore
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository, content_digest

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMPC"
_ENCRYPTED = (Path(__file__).parent / "encrypted.pdf").read_bytes()


def _hash(data: bytes) -> str:
    return content_digest(io.BytesIO(data))[0]


def test_parse_gives_the_pages_or_unreadable_and_refuses_bytes_of_another_hash() -> None:
    heft, broken = text_pdf(["Lager", ""]), text_pdf(["kaputt"])[:200]

    assert media_text.parse(heft, _hash(heft)) == Pages(("Lager", ""))
    assert media_text.parse(_ENCRYPTED, _hash(_ENCRYPTED)) == Unreadable()
    assert media_text.parse(broken, _hash(broken)) == Unreadable()
    assert media_text.parse(text_pdf(["fremd"]), _hash(heft)) == HashMismatch()


def test_readable_names_each_pdf_once() -> None:
    heft, kopie, akte = MediaRef("a.pdf", "h1"), MediaRef("b.pdf", "h1"), MediaRef("c.pdf", "h2")

    readable = media_text.readable((heft, MediaRef("d.jpg", "h3"), kopie, akte))
    assert [ref.content_hash for ref in readable] == ["h1", "h2"]


def test_the_fill_of_a_gone_article_reads_nothing() -> None:
    assert media_text.fill(Archive.of(InMemoryObjectStore()), _ULID) == {}


@pytest.fixture
def store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


def _save(
    store: ObjectStore, ulid: str, *files: tuple[str, bytes], version: int = 0
) -> tuple[MediaRef, ...]:
    """Save Article ``ulid`` over ``version`` with ``files`` (name, bytes) as its media."""
    articles = ArticleRepository(store)
    refs = tuple(articles.add_media(ulid, name, io.BytesIO(data)) for name, data in files)
    articles.save(make_article(ulid, collection_id="ROOT", media=refs), version, changed_by="t")
    return refs


def _pages(ref: MediaRef) -> list[tuple[int, str]]:
    rows = MediaText.objects.filter(content_hash=ref.content_hash).order_by("page")
    return list(rows.values_list("page", "text"))


@pytest.mark.django_db
def test_each_pdf_of_the_article_is_read_once(store: InMemoryObjectStore) -> None:
    heft, foto = _save(store, _ULID, ("Heft.pdf", text_pdf(["Lager", "Wald"])), ("a.jpg", b"jpeg"))

    assert media_text.missing(Archive.of(store)) == (_ULID,)
    assert media_text.fill(Archive.of(store), _ULID) == {
        heft.content_hash: Pages(("Lager", "Wald"))
    }
    assert _pages(heft) == [(1, "Lager"), (2, "Wald")]
    assert _pages(foto) == []
    assert media_text.fill(Archive.of(store), _ULID) == {}
    assert media_text.missing(Archive.of(store)) == ()


@pytest.mark.django_db
def test_a_pdf_that_gives_no_text_is_not_read_again(store: InMemoryObjectStore) -> None:
    (locked,) = _save(store, _ULID, ("Geheim.pdf", _ENCRYPTED))

    assert media_text.fill(Archive.of(store), _ULID) == {locked.content_hash: Unreadable()}
    assert _pages(locked) == [(0, "")]
    assert media_text.missing(Archive.of(store)) == ()


@pytest.mark.django_db
def test_bytes_that_do_not_match_their_hash_store_nothing_and_alarm(
    store: InMemoryObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    (heft,) = _save(store, _ULID, ("Heft.pdf", text_pdf(["Lager"])))
    articles = ArticleRepository(store)
    store.write_atomic(articles.media_key(_ULID, heft), text_pdf(["fremder Text"]))

    assert media_text.fill(Archive.of(store), _ULID) == {heft.content_hash: HashMismatch()}
    assert MediaText.objects.count() == 0
    assert f"media {heft.content_hash} of {_ULID} does not match its hash" in caplog.messages
    assert media_text.missing(Archive.of(store)) == (_ULID,)


@pytest.mark.django_db
def test_a_file_no_longer_on_the_article_is_not_read(store: InMemoryObjectStore) -> None:
    (old,) = _save(store, _ULID, ("Alt.pdf", text_pdf(["alt"])))
    (new,) = _save(store, _ULID, ("Neu.pdf", text_pdf(["neu"])), version=1)

    assert media_text.fill(Archive.of(store), _ULID) == {new.content_hash: Pages(("neu",))}
    assert _pages(old) == []
    assert _pages(new) == [(1, "neu")]


@pytest.mark.django_db
def test_one_bad_file_never_stops_the_others(store: InMemoryObjectStore) -> None:
    gone, broken, good = _save(
        store,
        _ULID,
        ("Weg.pdf", text_pdf(["weg"])),
        ("Kaputt.pdf", text_pdf(["kaputt"])[:200]),
        ("Gut.pdf", text_pdf(["gut"])),
    )
    store.delete(ArticleRepository(store).media_key(_ULID, gone))

    assert media_text.fill(Archive.of(store), _ULID) == {
        broken.content_hash: Unreadable(),
        good.content_hash: Pages(("gut",)),
    }
    assert (_pages(gone), _pages(broken), _pages(good)) == ([], [(0, "")], [(1, "gut")])


@pytest.mark.django_db
def test_rebuild_index_reads_the_missing_text_inline(tmp_path: Path) -> None:
    store = LocalFsObjectStore(tmp_path / "canonical")
    heft, *_ = _save(
        store,
        _ULID,
        ("Heft.pdf", text_pdf(["Lager"])),
        ("Akte.pdf", text_pdf(["Wald"])),
        ("Geheim.pdf", _ENCRYPTED),
    )
    out = io.StringIO()

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        call_command("rebuild_index", stdout=out)

    assert _pages(heft) == [(1, "Lager")]
    assert "page text read: 2 files, 1 unreadable, 0 not matching their hash" in out.getvalue()


class _DiesOnSecond(InMemoryObjectStore):
    """A store whose read of ``dies.pdf`` kills the job, as a reader crash would."""

    def open_stream(self, key: str) -> BinaryIO:
        if key.endswith("dies.pdf"):
            raise SystemExit("reader crashed")
        return super().open_stream(key)


@pytest.mark.django_db
def test_a_file_read_before_a_crash_stays_stored() -> None:
    store = _DiesOnSecond()
    first, _ = _save(
        store, _ULID, ("lives.pdf", text_pdf(["Sommerlager"])), ("dies.pdf", text_pdf(["x"]))
    )

    with pytest.raises(SystemExit):
        media_text.fill(Archive.of(store), _ULID)

    assert _pages(first) == [(1, "Sommerlager")]
