"""The 4.6 Artikel detail read view (`/artikel/<ulid>`, `article_detail`) — the Lesesaal read page.

The leak surface (spec §9): per-tier projection honesty. One template fed a `visible`-projected
Article, so archivist-only fields (Standort/physical_location, Weitere Angaben/custom) are FLOORED
before the template and cannot reach a member/public body even by a template mistake. These assert
field-VALUE absence (not just a missing class), draft 404 discipline, the action row + ENTWURF badge
for archivists, the EDTF human-vs-mono double render, and no amber/red on a member view.

Pure request-handling against a local FS store (load + resolve + visible) — no Postgres.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection

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
            custom=(("Bearbeitung", _CUSTOM_VALUE),),
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
    return client_as(viewer).get(f"/artikel/{ulid}{query}").content.decode()


# --- the read view renders the record ---------------------------------------------


def test_detail_renders_title_and_record_card(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "Sommerfahrt 1962" in body
    assert "F12" in body  # Signatur
    assert "K. Meyer" in body  # Autor
    assert "Harz" in body  # Ort
    assert "Zeitschrift" in body  # Typ (document_type preferred)
    assert "Erste Zeile." in body  # Beschreibung prose


def test_detail_renders_edtf_human_and_mono(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert "Juli 1962" in body  # human German under the title (edtf_to_german)
    assert "1962-07" in body  # raw machine value in the card mono row


def test_detail_renders_cover_and_filmstrip_thumbs(corpus: _DetailArchive) -> None:
    body = _body(Public(), corpus.pub)
    assert f"/media/{corpus.pub}/{corpus.cover_hash}/thumb" in body  # cover
    assert f"/media/{corpus.pub}/{corpus.second_hash}/thumb" in body  # filmstrip plate
    assert "Am Lagerfeuer" in body  # cover caption
    assert (
        f'href="/media/{corpus.pub}/{corpus.second_hash}"' in body
    )  # plate → full gated byte route
    # no raw bytes inlined — only /media/ URLs
    assert "data:image" not in body


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


def test_archivist_only_fields_are_the_only_member_vs_archivist_diff(
    corpus: _DetailArchive,
) -> None:
    # guards against a NEW archivist-only field silently reaching members: the two renders must
    # differ ONLY by the archivist-only values + the archivist chrome (action row, its markers).
    member = _body(Member(groups=()), corpus.pub)
    archivist = _body(Archivist(), corpus.pub)
    # both carry the shared reading structure
    for shared in ("Sommerfahrt 1962", "Juli 1962", "F12", "K. Meyer", "Erste Zeile."):
        assert shared in member
        assert shared in archivist
    # the archivist-only VALUES appear only for the archivist
    assert _STANDORT in archivist and _STANDORT not in member
    assert _CUSTOM_VALUE in archivist and _CUSTOM_VALUE not in member


# --- draft visibility (archivist-only, §9) ----------------------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=())])
def test_draft_is_404_for_non_archivist(corpus: _DetailArchive, viewer: Viewer) -> None:
    response = client_as(viewer).get(f"/artikel/{corpus.draft}")
    assert_denied(response)  # denied — indistinguishable status from a nonexistent ulid


def test_draft_is_200_with_badge_and_actions_for_archivist(corpus: _DetailArchive) -> None:
    response = client_as(Archivist()).get(f"/artikel/{corpus.draft}")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Entwurf" in body  # ENTWURF badge
    assert "/bearbeiten" in body  # action row present


# --- action row / archivist chrome ------------------------------------------------


def test_member_published_view_carries_no_action_row(corpus: _DetailArchive) -> None:
    body = _body(Member(groups=()), corpus.pub)
    assert 'class="actions"' not in body  # no action row for a member
    assert "/bearbeiten" not in body


def test_member_published_view_has_no_amber_or_red(corpus: _DetailArchive) -> None:
    # §0/§9: a member published view carries NO draft (amber) or error (red) chrome.
    body = _body(Member(groups=()), corpus.pub)
    assert 'class="badge entwurf"' not in body
    assert "--draft" not in body
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


# --- design-gate fixups ------------------------------------------------------------


def test_cover_platte_links_to_full_image(corpus: _DetailArchive) -> None:
    # LOW-MED: the cover always links its full gated byte route, so a single-media article (no
    # filmstrip) still has a path to the full image.
    body = _body(Public(), corpus.pub)
    assert f'href="/media/{corpus.pub}/{corpus.cover_hash}"' in body


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


def test_zurueck_default_when_no_return_query(corpus: _DetailArchive) -> None:
    # no ?zurueck → the return link is a bare "/" (unchanged behavior).
    body = _body(Public(), corpus.pub)
    assert '<a class="back" href="/">' in body


def test_zurueck_round_trips_a_clean_search_query(corpus: _DetailArchive) -> None:
    # MED: the return link carries the search back (q + facet + page), sanitized through the browse
    # param whitelist and re-serialized (never echoed raw).
    body = _body(Public(), corpus.pub, "?zurueck=q%3Dfahrt%26schlagwort%3Dsommer%26seite%3D2")
    assert 'class="back"' in body
    for fragment in ("q=fahrt", "schlagwort=sommer", "seite=2"):
        assert fragment in body


def test_zurueck_drops_unknown_and_pane_params(corpus: _DetailArchive) -> None:
    # the sanitizer whitelists known search params only: an injected artikel= (pane state) or a
    # bogus key must not survive into the return link (no reflection / existence oracle).
    body = _body(Public(), corpus.pub, "?zurueck=q%3Dfahrt%26artikel%3DXYZ%26evil%3D%3Cscript%3E")
    assert "q=fahrt" in body
    assert "artikel=" not in body
    assert "evil" not in body
    assert "script" not in body.lower().split('class="back"')[1][:200]


def test_zurueck_malformed_falls_back_to_root(corpus: _DetailArchive) -> None:
    # a ?zurueck with no recognizable search params → the return link is a bare "/".
    body = _body(Public(), corpus.pub, "?zurueck=%7Bnot-a-query%7D")
    assert '<a class="back" href="/">' in body
