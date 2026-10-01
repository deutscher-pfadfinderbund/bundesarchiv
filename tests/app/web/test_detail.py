"""The 4.6 Artikel detail read view (`/articles/<ulid>`, `article_detail`) — the Lesesaal read page.

The leak surface (spec §9): per-tier projection honesty. One template fed a `visible`-projected
Article, so archivist-only fields (Standort/physical_location, Weitere Angaben/custom) are FLOORED
before the template and cannot reach a member/public body even by a template mistake. These assert
field-VALUE absence (not just a missing class), draft 404 discipline, the archivist's tools, and no
red on a member view.

Pure request-handling against a local FS store (load + resolve + visible) — no Postgres.
"""

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

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import generate_thumbnail
from bundesarchiv.app.web.media_views import media_url, thumbnail_url
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle, MediaRef
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

# The detail page only PRINTS the Bestand id (as a ?bestand= facet link) and never routes on it, so
# a mnemonic reads better here than a ULID.
FOTOS = "FOTOS"

PUB = new_ulid()
DRAFT = new_ulid()
MARKUP = new_ulid()

_STANDORT = "Magazin 3, Regal 7"
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
    """Overrides the standard corpus: the read page needs ONE richly-populated published article
    (all card fields + two media + archivist-only Standort/custom) alongside a draft and a
    markup-bearing record — content the frozen standard shape cannot hold. Media blobs are stored
    via ``add_media`` (the repository refuses an Article referencing an unstored blob), and the
    returned refs' real content hashes travel back for the media-URL assertions."""
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
            physical_location=_STANDORT,
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
    # A record whose free-text fields carry HTML markup — the escaping pin (§ leak surface): the
    # template auto-escapes every value, so a <script> in the body/title/caption round-trips inert.
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
    assert '<time datetime="1962-07">1962-07</time>' in body  # Datierung
    assert "Erste Zeile." in body  # Beschreibung prose


def test_a_tile_shows_a_thumbnail_only_once_the_cache_holds_one(
    corpus: _DetailArchive, tmp_path: Path
) -> None:
    thumbs = tmp_path / "thumbs"
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        assert generate_thumbnail(Archive.canonical().store, corpus.pub, corpus.cover_hash, thumbs)
        body = _body(Public(), corpus.pub)
    images = re.findall(r'<img [^>]*src="([^"]*)"', body)
    assert thumbnail_url(corpus.pub, corpus.cover_hash) in images
    assert thumbnail_url(corpus.pub, corpus.second_hash) not in body  # nothing that could break
    assert "b.png" in body  # the uncached file's tile names it
    assert "data:image" not in body  # no bytes inlined


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


def test_every_tile_opens_and_offers_to_save_its_original(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    originals = {media_url(corpus.pub, h) for h in (corpus.cover_hash, corpus.second_hash)}
    assert originals <= set(page_hrefs(body))
    assert set(download_hrefs(body)) == originals
    assert len(download_hrefs(body)) == 3  # the cover once under the Platte, then every plate


# --- projection / per-tier (the leak surface, §9) ---------------------------------


def test_member_never_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert _STANDORT not in body  # physical_location floored to None → row absent
    assert _CUSTOM_VALUE not in body  # custom floored to () → rows absent
    assert "Standort" not in body


def test_public_never_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert _STANDORT not in body
    assert _CUSTOM_VALUE not in body


def test_archivist_sees_archivist_only_field_values(corpus: _DetailArchive) -> None:
    body = _body(Archivist(), corpus.pub)
    assert _STANDORT in body
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
    assert archivist - member - tools == {"Standort", _STANDORT, _CUSTOM_KEY, _CUSTOM_VALUE}


# --- draft visibility (archivist-only, §9) ----------------------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=())])
def test_draft_is_404_for_non_archivist(corpus: _DetailArchive, viewer: Viewer) -> None:
    response = client_as(viewer).get(f"/articles/{corpus.draft}")
    assert_denied(response)  # denied — indistinguishable status from a nonexistent ulid


def test_draft_is_200_and_closes_with_publish_for_archivist(corpus: _DetailArchive) -> None:
    response = client_as(Archivist()).get(f"/articles/{corpus.draft}")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Veröffentlichen" in body
    assert "Als Entwurf zurückziehen" not in body  # it can never become active on a draft
    assert "/edit" in body


def test_published_record_offers_withdraw_to_archivist(corpus: _DetailArchive) -> None:
    body = _body(Archivist(), corpus.pub)
    assert "Als Entwurf zurückziehen" in body
    assert "Veröffentlichen" not in body


# --- action row / archivist chrome ------------------------------------------------


def test_member_published_view_carries_no_action_row(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert 'class="actions"' not in body  # no action row for a member
    assert "/edit" not in body


def test_member_published_view_has_no_draft_mark_or_red(corpus: _DetailArchive) -> None:
    # §0/§9: a member published view carries NO draft mark or error (red) chrome.
    body = _body(Member(groups=()), corpus.pub)
    assert draft_mark() not in body
    assert "--error" not in body


# --- Bestand + Schlagworte links (the browsing loop) ------------------------------


def test_bestand_breadcrumb_links_into_collection_facet(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "Fotografien" in body  # leaf collection name
    assert "?bestand=FOTOS" in body  # links into the collection facet


def test_schlagworte_link_into_tag_facet(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "?schlagwort=fahrt" in body
    assert "?schlagwort=sommer" in body


# --- escaping: free-text values round-trip inert (the leak-surface pin) -------------


def test_markup_bearing_fields_render_escaped(corpus: _DetailArchive) -> None:
    # The detail template auto-escapes every value (no |safe / mark_safe anywhere). A <script> in the
    # title, body, creator, or a media caption must round-trip as escaped text — never as live markup
    # (stored-XSS closed: an archivist-typed field cannot execute in a reader's browser).
    body = _body(Public(), corpus.markup)
    # the payloads appear ESCAPED …
    assert "&lt;script&gt;alert(&#x27;body&#x27;)&lt;/script&gt;" in body
    assert "&lt;script&gt;alert(&#x27;titel&#x27;)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=1&gt;" in body  # the caption
    # … and NEVER as executable markup.
    assert "<script>alert" not in body
    assert "<img src=x onerror=1>" not in body
