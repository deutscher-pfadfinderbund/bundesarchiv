"""The Article detail page (``/articles/<ulid>``): no archivist-only value reaches a member or
public body."""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.test import override_settings
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    Corpus,
    client_as,
    download_hrefs,
    draft_mark,
    make_article,
    make_collection,
    page_hrefs,
)

from bundesarchiv.app import legacy
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import generate_thumbnail
from bundesarchiv.app.web import vocab
from bundesarchiv.app.web.browse_views import media_tiles
from bundesarchiv.app.web.media_urls import display_url, media_url, thumbnail_url
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import (
    ULID,
    Audience,
    AudienceTier,
    Change,
    Lifecycle,
    MediaRef,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence._layout import ARTICLES
from bundesarchiv.persistence._writer import history_key

# The detail page only PRINTS the Collection id (as a ?collection= facet link) and never routes on it, so
# a mnemonic reads better here than a ULID.
FOTOS = "FOTOS"

PUB = new_ulid()
DRAFT = new_ulid()
MARKUP = new_ulid()

_LOCATION = "Magazin 3, Regal 7"
_CUSTOM_KEY = "Bearbeitung"
_CUSTOM_VALUE = "Restaurierung 1998"


def _png(color: tuple[int, int, int]) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


@dataclass(frozen=True)
class _DetailArchive:
    """The record ulids of this suite's archive plus the two media content hashes, which only the
    store can hand out."""

    pub: str
    draft: str
    markup: str
    cover_hash: str
    second_hash: str


@pytest.fixture
def corpus(make_corpus: Callable[[], Corpus]) -> _DetailArchive:
    """Overrides the standard corpus. Media go through ``add_media``: the repository refuses an
    Article naming an unstored blob."""
    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    cover = archive.articles.add_media(
        PUB, "a.png", io.BytesIO(_png((200, 40, 60))), media_type="image/png"
    )
    second = archive.articles.add_media(
        PUB, "b.png", io.BytesIO(_png((40, 200, 60))), media_type="image/png"
    )
    archive.add_article(
        make_article(
            PUB,
            collection_id=FOTOS,
            title="Sommerfahrt 1962",
            body="Erste Zeile.\n\nZweite Zeile.",
            ref_code="F12",
            media_type="Foto(s)",
            document_type="Zeitschrift",
            tags=("fahrt", "sommer"),
            date=EdtfDate("1962-07"),
            creator="K. Meyer",
            subject_place="Harz",
            physical_location=_LOCATION,
            custom=((_CUSTOM_KEY, _CUSTOM_VALUE),),
            media=(
                MediaRef(cover.filename, cover.content_hash, caption="Am Lagerfeuer"),
                MediaRef(second.filename, second.content_hash, caption="Gruppenbild"),
            ),
        )
    )
    archive.add_article(
        make_article(DRAFT, collection_id=FOTOS, lifecycle=Lifecycle.DRAFT, title="Entwurf")
    )
    evil = archive.articles.add_media(
        MARKUP, "e.png", io.BytesIO(_png((90, 90, 90))), media_type="image/png"
    )
    archive.add_article(
        make_article(
            MARKUP,
            collection_id=FOTOS,
            title="<script>alert('titel')</script>",
            body="Harmlos.\n\n<script>alert('body')</script>",
            creator="<b>Autor</b>",
            media=(MediaRef(evil.filename, evil.content_hash, caption="<img src=x onerror=1>"),),
        )
    )
    return _DetailArchive(PUB, DRAFT, MARKUP, cover.content_hash, second.content_hash)


def _body(viewer: Viewer, ulid: str, query: str = "") -> str:
    return client_as(viewer).get(f"/articles/{ulid}{query}").content.decode()


# --- the read view renders the record ---------------------------------------------


def test_detail_renders_title_and_origin(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "Sommerfahrt 1962" in body
    assert "F12" in body  # Signatur
    assert "von K. Meyer" in body  # Urheber
    assert "Harz" in body  # Ort
    assert "Zeitschrift" in body  # Typ (document_type preferred)
    assert '<time datetime="1962-07">Juli 1962</time>' in body  # Datierung
    assert "Erste Zeile." in body  # Beschreibung prose


def test_a_tile_shows_a_thumbnail_only_once_the_cache_holds_one(
    corpus: _DetailArchive, tmp_path: Path
) -> None:
    thumbs = tmp_path / "thumbs"
    second = thumbnail_url(corpus.pub, corpus.second_hash)
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        before = _body(Public(), corpus.pub)
        assert generate_thumbnail(
            Archive.canonical().store, ULID(corpus.pub), corpus.second_hash, thumbs
        )
        after = _body(Public(), corpus.pub)
    assert second not in before
    assert "b.png" in before
    assert second in re.findall(r'<img [^>]*src="([^"]*)"', after)
    assert "data:image" not in after  # no bytes inlined


def test_the_page_leads_with_the_original_of_an_image_a_browser_draws(
    corpus: _DetailArchive,
) -> None:
    images = re.findall(r'<img [^>]*src="([^"]*)"', _body(Public(), corpus.pub))
    assert images[0] == media_url(corpus.pub, corpus.cover_hash)  # sharp at any width


def test_a_pdf_leads_the_page_with_its_first_page_once_derived(
    make_corpus: Callable[[], Corpus], tmp_path: Path
) -> None:
    from PIL import Image

    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    page = io.BytesIO()
    Image.new("RGB", (60, 80), (240, 240, 230)).save(page, format="PDF")
    page.seek(0)
    ulid = new_ulid()
    pdf = archive.articles.add_media(ulid, "Protokoll.pdf", page, media_type="application/pdf")
    archive.add_article(make_article(ulid, collection_id=FOTOS, media=(pdf,)))
    thumbs = tmp_path / "thumbs"
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        assert generate_thumbnail(Archive.canonical().store, ulid, pdf.content_hash, thumbs)
        images = re.findall(r'<img [^>]*src="([^"]*)"', _body(Public(), ulid))
    assert images[0] == thumbnail_url(ulid, pdf.content_hash)


def test_each_tile_brings_its_ratio_and_an_image_its_display_url_to_the_page(
    make_corpus: Callable[[], Corpus], tmp_path: Path
) -> None:
    """The ratio is the image's as shown (its tile's), unknown until the tile exists; only an image
    has a display version."""
    from PIL import Image

    def encoded(size: tuple[int, int], format: str) -> io.BytesIO:
        buf = io.BytesIO()
        Image.new("RGB", size, (240, 240, 230)).save(buf, format=format)
        buf.seek(0)
        return buf

    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    ulid = new_ulid()
    photo = archive.articles.add_media(ulid, "a.png", encoded((960, 640), "PNG"), "image/png")
    pdf = archive.articles.add_media(ulid, "b.pdf", encoded((60, 80), "PDF"), "application/pdf")
    untiled = archive.articles.add_media(ulid, "c.png", encoded((50, 50), "PNG"), "image/png")
    archive.add_article(make_article(ulid, collection_id=FOTOS, media=(photo, pdf, untiled)))
    thumbs = tmp_path / "thumbs"
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        for ref in (photo, pdf):
            assert generate_thumbnail(Archive.canonical().store, ulid, ref.content_hash, thumbs)
        context = client_as(Public()).get(f"/articles/{ulid}").context
    tiles = (context["cover"], *context["more_media"])
    assert [t.aspect[0] / t.aspect[1] if t.aspect else None for t in tiles] == [1.5, 0.75, None]
    assert [t.display_url for t in tiles] == [
        display_url(ulid, photo.content_hash),
        "",
        display_url(ulid, untiled.content_hash),
    ]


def test_every_tile_opens_and_offers_to_save_its_original(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    originals = {media_url(corpus.pub, h) for h in (corpus.cover_hash, corpus.second_hash)}
    assert originals <= set(page_hrefs(body))
    assert set(download_hrefs(body)) == originals


def test_every_file_on_the_page_has_a_download_link(
    make_corpus: Callable[[], Corpus],
) -> None:
    """A PDF or audio tile in the rows carries its own line; an image's lives in the lightbox."""
    from PIL import Image

    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    ulid = new_ulid()

    def png(color: int) -> io.BytesIO:
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), (color, 0, 0)).save(buf, format="PNG")
        buf.seek(0)
        return buf

    files = (
        archive.articles.add_media(ulid, "a.png", png(10), "image/png"),
        archive.articles.add_media(ulid, "b.pdf", io.BytesIO(b"%PDF-1.4 b"), "application/pdf"),
        archive.articles.add_media(ulid, "c.mp3", io.BytesIO(b"ID3 c"), "audio/mpeg"),
        archive.articles.add_media(ulid, "d.png", png(20), "image/png"),
    )
    archive.add_article(make_article(ulid, collection_id=FOTOS, media=files))
    body = _body(Public(), ulid)
    assert set(download_hrefs(body)) == {media_url(ulid, f.content_hash) for f in files}


def test_a_file_without_a_thumbnail_gets_the_glyph_of_its_kind() -> None:
    files = (
        MediaRef("a.mp4", "0" * 64, media_type="video/mp4"),
        MediaRef("b.mp3", "1" * 64, media_type="audio/mpeg"),
        MediaRef("c.pdf", "2" * 64, media_type="application/pdf"),
    )
    tiles = media_tiles(new_ulid(), files)
    assert [(t.thumb_url, t.glyph) for t in tiles] == [
        ("", "video-file"),
        ("", "audio-file"),
        ("", "file-present"),
    ]


def test_a_first_file_without_a_preview_leads_the_plates_not_a_cover(
    make_corpus: Callable[[], Corpus],
) -> None:
    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    ulid = new_ulid()
    files = (
        archive.articles.add_media(ulid, "a.mp4", io.BytesIO(b"mp4 a"), "video/mp4"),
        archive.articles.add_media(ulid, "b.mp3", io.BytesIO(b"ID3 b"), "audio/mpeg"),
    )
    archive.add_article(make_article(ulid, collection_id=FOTOS, media=files))
    context = client_as(Public()).get(f"/articles/{ulid}").context
    assert context["cover"] is None
    assert [t.name for t in context["more_media"]] == ["a.mp4", "b.mp3"]


# --- projection / per-tier (the leak surface, §9) ---------------------------------


def test_member_never_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert _LOCATION not in body  # physical_location floored to None → row absent
    assert _CUSTOM_VALUE not in body  # custom floored to () → rows absent
    assert "Standort" not in body


def test_public_never_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert _LOCATION not in body
    assert _CUSTOM_VALUE not in body


def test_archivist_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Archivist(), corpus.pub)
    assert _LOCATION in body
    assert _CUSTOM_VALUE in body
    assert "Standort" in body


def _texts(viewer: Viewer, ulid: str) -> set[str]:
    """The page's visible text nodes, whitespace-normalized."""
    parser = _TextNodes()
    parser.feed(_body(viewer, ulid))
    return parser.texts


class _TextNodes(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.texts: set[str] = set()

    def handle_data(self, data: str) -> None:
        if text := " ".join(data.split()):
            self.texts.add(text)


def test_archivist_only_fields_are_the_only_member_vs_archivist_diff(
    corpus: _DetailArchive,
) -> None:
    """Beyond the archivist's tools, which a record without archivist-only values shows too, the
    two renders differ only by the floored fields: nothing else is gated in the template."""
    member = _texts(Member(groups=()), corpus.pub)
    archivist = _texts(Archivist(), corpus.pub)
    tools = _texts(Archivist(), corpus.markup) - _texts(Member(groups=()), corpus.markup)
    assert member <= archivist
    # "intern" marks those labels for the archivist: what a member does not see
    assert archivist - member - tools == {
        "Standort",
        "intern",
        _LOCATION,
        _CUSTOM_KEY,
        _CUSTOM_VALUE,
    }


# --- the last change: an archivist's alone (owner ruling 2026-10-21) --------------

_EDITOR = "anna.k"


@pytest.fixture
def edited(make_corpus: Callable[[], Corpus]) -> Corpus:
    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    archive.articles.save(make_article(PUB, collection_id=FOTOS), 0, changed_by=_EDITOR)
    return archive


def _change_of(archive: Corpus, ulid: str) -> Change:
    change = archive.articles.load(ULID(ulid)).change
    assert change is not None
    return change


@pytest.mark.parametrize("viewer", [Public(), Member(groups=()), Member(groups=("Leitung",))])
def test_no_non_archivist_learns_who_last_changed_a_record(edited: Corpus, viewer: Viewer) -> None:
    assert _EDITOR not in _body(viewer, PUB)


def test_an_archivist_sees_who_last_changed_a_record_and_when(edited: Corpus) -> None:
    body = _body(Archivist(), PUB)
    assert _EDITOR in body
    assert vocab.day(_change_of(edited, PUB).at) in body


def test_an_imported_version_names_the_old_archive_not_the_import(
    make_corpus: Callable[[], Corpus],
) -> None:
    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    archive.articles.save(make_article(PUB, collection_id=FOTOS), 0, changed_by=legacy.CHANGED_BY)
    body = _body(Archivist(), PUB)
    assert vocab.day(_change_of(archive, PUB).at) in body
    assert legacy.CHANGED_BY not in body


def test_a_readme_without_a_change_record_renders_without_the_line(edited: Corpus) -> None:
    """A README written before ADR 0019 carries no change record."""
    day = vocab.day(_change_of(edited, PUB).at)
    readme = edited.root / ARTICLES.readme_key(ULID(PUB))
    readme.write_text(
        "".join(
            line
            for line in readme.read_text().splitlines(keepends=True)
            if not line.startswith(("changed_at:", "changed_by:"))
        )
    )
    response = client_as(Archivist()).get(f"/articles/{PUB}")
    assert response.status_code == 200
    assert day not in response.content.decode()
    assert _EDITOR not in response.content.decode()


# --- who edited when: every version, an archivist's alone (#71 slice 2) -----------

_FIRST_EDITOR, _SECOND_EDITOR = "anna.k", "ben.m"


@pytest.fixture
def twice_edited(make_corpus: Callable[[], Corpus]) -> Corpus:
    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    article = make_article(PUB, collection_id=FOTOS)
    archive.articles.save(article, 0, changed_by=_FIRST_EDITOR)
    archive.articles.save(article, 1, changed_by=_SECOND_EDITOR)
    return archive


@pytest.mark.parametrize("viewer", [Public(), Member(groups=()), Member(groups=("Leitung",))])
def test_no_non_archivist_learns_who_edited_any_version(
    twice_edited: Corpus, viewer: Viewer
) -> None:
    body = _body(viewer, PUB)
    assert _FIRST_EDITOR not in body
    assert _SECOND_EDITOR not in body


def test_an_archivist_sees_every_version_with_its_date_and_editor(twice_edited: Corpus) -> None:
    articles = twice_edited.articles
    versions = articles.versions(articles.load(ULID(PUB)))
    body = _body(Archivist(), PUB)
    assert [number for number, _ in versions] == [1, 2]
    for _, change in versions:
        assert change is not None
        assert change.by in body
        assert change.at.isoformat() in body


def test_an_unreadable_kept_version_leaves_the_page_standing(twice_edited: Corpus) -> None:
    kept = twice_edited.root / history_key(ARTICLES.folder(ULID(PUB)), 1)
    kept.write_bytes(b"\xff\xfe\x00")
    response = client_as(Archivist()).get(f"/articles/{PUB}")
    assert response.status_code == 200
    assert _SECOND_EDITOR in response.content.decode()


# --- draft visibility (archivist-only, §9) ----------------------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=())])
def test_draft_is_404_for_non_archivist(corpus: _DetailArchive, viewer: Viewer) -> None:
    response = client_as(viewer).get(f"/articles/{corpus.draft}")
    assert_denied(response)


@pytest.mark.parametrize(
    "misspell",
    [str.lower, lambda u: u[:-1] + "U", lambda u: "8" + u[1:], lambda u: u + "0"],
    ids=["lowercase", "excluded-letter", "beyond-128-bits", "too-long"],
)
def test_a_misspelled_ulid_is_denied_before_the_store_is_asked(
    corpus: _DetailArchive, misspell: Callable[[str], str]
) -> None:
    """A case-insensitive filesystem (macOS) would find the lowercase folder."""
    assert_denied(client_as(Archivist()).get(f"/articles/{misspell(corpus.pub)}"))


def test_draft_is_200_and_closes_with_publish_for_archivist(corpus: _DetailArchive) -> None:
    response = client_as(Archivist()).get(f"/articles/{corpus.draft}")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Veröffentlichen" in body
    assert "Als Entwurf zurückziehen" not in body  # it can never become active on a draft
    assert "/edit" in body


def test_published_record_offers_no_publish_to_archivist(corpus: _DetailArchive) -> None:
    # withdrawing is the form's Status, next to Speichern: the page's menu has no entry for it
    body = _body(Archivist(), corpus.pub)
    assert "Veröffentlichen" not in body
    assert "Als Entwurf zurückziehen" not in body


def test_the_files_after_the_cover_leave_the_cover_out(corpus: _DetailArchive) -> None:
    strip = _body(Public(), corpus.pub).split('class="media-rows"', 1)[1].split("</section>", 1)[0]
    assert media_url(corpus.pub, corpus.second_hash) in strip
    assert media_url(corpus.pub, corpus.cover_hash) not in strip


# --- action row / archivist chrome ------------------------------------------------


def test_member_published_view_carries_no_action_row(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert 'class="actions"' not in body
    assert "/edit" not in body


def test_member_published_view_has_no_draft_mark_or_red(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert draft_mark() not in body
    assert "--error" not in body


# --- Collection + Schlagworte links (the browsing loop) ------------------------------


def test_collection_breadcrumb_links_into_collection_facet(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "Fotografien" in body
    assert "?collection=FOTOS" in body


def test_tags_link_into_tag_facet(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "?tag=fahrt" in body
    assert "?tag=sommer" in body


# --- escaping: free-text values round-trip inert (the leak-surface pin) -------------


def test_markup_bearing_fields_render_escaped(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.markup)
    assert "&lt;script&gt;alert(&#x27;body&#x27;)&lt;/script&gt;" in body
    assert "&lt;script&gt;alert(&#x27;titel&#x27;)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=1&gt;" in body  # the caption
    assert "<script>alert" not in body
    assert "<img src=x onerror=1>" not in body


def test_an_images_alt_is_its_description_else_its_caption_else_its_file_name(
    make_corpus: Callable[[], Corpus],
) -> None:
    """One rule for the cover, the row tiles and the lightbox; a blank stored alt counts as none."""
    from dataclasses import replace

    from PIL import Image

    archive = make_corpus()
    archive.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    ulid = new_ulid()

    def add(name: str, shade: int, alt: str | None = None, caption: str | None = None) -> MediaRef:
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (shade, 0, 0)).save(buf, format="PNG")
        buf.seek(0)
        return replace(
            archive.articles.add_media(ulid, name, buf, "image/png"), alt=alt, caption=caption
        )

    refs = (
        add("a.png", 1, alt="Beschreibung", caption="Unterschrift"),
        add("b.png", 2, caption="Nur Unterschrift"),
        add("c.png", 3, alt="  "),
        add("d.png", 4, alt="  ", caption=" \n"),
    )
    archive.add_article(make_article(ulid, collection_id=FOTOS, media=refs))
    body = client_as(Public()).get(f"/articles/{ulid}").content.decode()
    alts = re.findall(r'<img [^>]*alt="([^"]*)"', body)
    # the cover (drawn from its original) and the lightbox (one figure per image)
    assert sorted(alts) == ["Beschreibung", "Beschreibung", "Nur Unterschrift", "c.png", "d.png"]
