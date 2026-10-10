"""The page text: which files are still unread, what a file's bytes give, and the fill — each PDF
of an Article's current media is read once, a file that gives no text is not read again, bytes that
do not match their hash store nothing, and one bad file never stops the others."""

import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import override_settings
from tests._articles import make_article
from tests._pdfs import text_pdf

from bundesarchiv.app import media_text
from bundesarchiv.app.media_text import HashMismatch, Pages, Unreadable
from bundesarchiv.domain.models import MediaRef
from bundesarchiv.index.models import MediaText
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
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


def test_unread_names_each_pdf_not_done_once() -> None:
    heft, kopie, done = MediaRef("a.pdf", "h1"), MediaRef("b.pdf", "h1"), MediaRef("c.pdf", "h2")

    unread = media_text.unread((heft, MediaRef("d.jpg", "h3"), kopie, done), {"h2"})
    assert [ref.content_hash for ref in unread] == ["h1"]


@pytest.fixture
def store(tmp_path: Path) -> LocalFsObjectStore:
    return LocalFsObjectStore(tmp_path / "canonical")


def _save(
    store: LocalFsObjectStore, ulid: str, *files: tuple[str, bytes], version: int = 0
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
def test_each_pdf_of_the_article_is_read_once(store: LocalFsObjectStore) -> None:
    heft, foto = _save(store, _ULID, ("Heft.pdf", text_pdf(["Lager", "Wald"])), ("a.jpg", b"jpeg"))

    assert media_text.missing(store) == (_ULID,)
    assert media_text.extract(store, _ULID) == 1
    assert _pages(heft) == [(1, "Lager"), (2, "Wald")]
    assert _pages(foto) == []
    assert media_text.extract(store, _ULID) == 0
    assert media_text.missing(store) == ()


@pytest.mark.django_db
def test_a_pdf_that_gives_no_text_is_not_read_again(store: LocalFsObjectStore) -> None:
    (locked,) = _save(store, _ULID, ("Geheim.pdf", _ENCRYPTED))

    assert media_text.extract(store, _ULID) == 1
    assert _pages(locked) == [(0, "")]
    assert media_text.missing(store) == ()


@pytest.mark.django_db
def test_bytes_that_do_not_match_their_hash_store_nothing(store: LocalFsObjectStore) -> None:
    (heft,) = _save(store, _ULID, ("Heft.pdf", text_pdf(["Lager"])))
    articles = ArticleRepository(store)
    store.write_atomic(articles.media_key(_ULID, heft), text_pdf(["fremder Text"]))

    assert media_text.extract(store, _ULID) == 0
    assert MediaText.objects.count() == 0
    assert media_text.missing(store) == (_ULID,)


@pytest.mark.django_db
def test_a_file_no_longer_on_the_article_is_not_read(store: LocalFsObjectStore) -> None:
    (old,) = _save(store, _ULID, ("Alt.pdf", text_pdf(["alt"])))
    (new,) = _save(store, _ULID, ("Neu.pdf", text_pdf(["neu"])), version=1)

    assert media_text.extract(store, _ULID) == 1
    assert _pages(old) == []
    assert _pages(new) == [(1, "neu")]


@pytest.mark.django_db
def test_one_bad_file_never_stops_the_others(store: LocalFsObjectStore) -> None:
    gone, broken, good = _save(
        store,
        _ULID,
        ("Weg.pdf", text_pdf(["weg"])),
        ("Kaputt.pdf", text_pdf(["kaputt"])[:200]),
        ("Gut.pdf", text_pdf(["gut"])),
    )
    store.delete(ArticleRepository(store).media_key(_ULID, gone))

    assert media_text.extract(store, _ULID) == 2
    assert (_pages(gone), _pages(broken), _pages(good)) == ([], [(0, "")], [(1, "gut")])


@pytest.mark.django_db
def test_rebuild_index_reads_the_missing_text_inline(
    store: LocalFsObjectStore, tmp_path: Path
) -> None:
    (heft,) = _save(store, _ULID, ("Heft.pdf", text_pdf(["Lager"])))

    with override_settings(BUNDESARCHIV_CANONICAL_ROOT=str(tmp_path / "canonical")):
        call_command("rebuild_index", stdout=io.StringIO())

    assert _pages(heft) == [(1, "Lager")]
