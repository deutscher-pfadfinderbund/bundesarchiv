"""The 4.6 Artikel detail read view (`/artikel/<ulid>`, `article_detail`) — the Lesesaal read page.

The leak surface (spec §9): per-tier projection honesty. One template fed a `visible`-projected
Article, so archivist-only fields (Standort/physical_location, Weitere Angaben/custom) are FLOORED
before the template and cannot reach a member/public body even by a template mistake. These assert
field-VALUE absence (not just a missing class), draft 404 discipline, the action row + ENTWURF badge
for archivists, the EDTF human-vs-mono double render, and no amber/red on a member view.

Pure request-handling against a local FS store (load + resolve + visible) — no Postgres.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    MediaRef,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-detail-dev-key"

_STANDORT = "Magazin 3, Regal 7"
_CUSTOM_VALUE = "Restaurierung 1998"


def _png(color: tuple[int, int, int]) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


class _Corpus:
    """A small FS archive with ONE richly-populated published article (all card fields + two media +
    archivist-only Standort/custom) and one draft, in a public collection under a named root — enough
    to exercise the record card, filmstrip, per-tier projection, and the draft gate. Media blobs are
    stored via ``add_media`` (the repository refuses an Article referencing an unstored blob), and
    the returned refs' real content hashes are captured for the media-URL assertions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self._build()

    def _build(self) -> None:
        collections = CollectionRepository(self.store)
        articles = ArticleRepository(self.store)
        collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
        collections.save(
            Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0
        )
        cover = articles.add_media(self.pub, "a.png", _png((200, 40, 60)), media_type="image/png")
        second = articles.add_media(self.pub, "b.png", _png((40, 200, 60)), media_type="image/png")
        self.cover_hash = cover.content_hash
        self.second_hash = second.content_hash
        articles.save(
            Article(
                ulid=self.pub,
                title="Sommerfahrt 1962",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                body="Erste Zeile.\n\nZweite Zeile.",
                ref_code="F 12",
                media_type="Fotografie",
                document_type="Porträt",
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
            ),
            0,
        )
        articles.save(
            Article(
                ulid=self.draft,
                title="Entwurf",
                collection_id="FOTOS",
                lifecycle=Lifecycle.DRAFT,
            ),
            0,
        )
        # A pure text record: no body AND no media — the state that maroons the card if the grid
        # isn't collapsed (design-gate HOLD).
        articles.save(
            Article(
                ulid=self.textonly,
                title="Nur Text",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                ref_code="F 20",
                creator="A. Autor",
            ),
            0,
        )
        # A single-media record: exactly ONE sheet → the cover Platte renders, but the filmstrip
        # register is omitted (§1: the cover already shows the only sheet). Pins the ≤1-media boundary.
        solo = articles.add_media(self.single, "s.png", _png((60, 60, 200)), media_type="image/png")
        self.single_hash = solo.content_hash
        articles.save(
            Article(
                ulid=self.single,
                title="Ein Blatt",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                media=(MediaRef(solo.filename, solo.content_hash, caption="Das einzige Blatt"),),
            ),
            0,
        )
        # A record whose free-text fields carry HTML markup — the escaping pin (§ leak surface): the
        # template auto-escapes every value, so a <script> in the body/title/caption round-trips inert.
        evil = articles.add_media(self.markup, "e.png", _png((90, 90, 90)), media_type="image/png")
        articles.save(
            Article(
                ulid=self.markup,
                title="<script>alert('titel')</script>",
                collection_id="FOTOS",
                lifecycle=Lifecycle.PUBLISHED,
                body="Harmlos.\n\n<script>alert('body')</script>",
                creator="<b>Autor</b>",
                media=(
                    MediaRef(evil.filename, evil.content_hash, caption="<img src=x onerror=1>"),
                ),
            ),
            0,
        )

    pub = new_ulid()
    draft = new_ulid()
    textonly = new_ulid()
    single = new_ulid()
    markup = new_ulid()


@pytest.fixture
def corpus(tmp_path: Path) -> _Corpus:
    return _Corpus(tmp_path / "canonical")


def _settings(corpus: _Corpus) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
    }


def _client_as(viewer: Viewer) -> Client:
    client = Client()
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _body(corpus: _Corpus, viewer: Viewer, ulid: str, query: str = "") -> str:
    with override_settings(**_settings(corpus)):
        return _client_as(viewer).get(f"/artikel/{ulid}{query}").content.decode()


# --- the read view renders the record ---------------------------------------------


def test_detail_renders_title_and_record_card(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert "Sommerfahrt 1962" in body
    assert "F 12" in body  # Signatur
    assert "K. Meyer" in body  # Autor
    assert "Harz" in body  # Ort
    assert "Porträt" in body  # Typ (document_type preferred)
    assert "Erste Zeile." in body  # Beschreibung prose


def test_detail_renders_edtf_human_and_mono(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert "Juli 1962" in body  # human German under the title (edtf_to_german)
    assert "1962-07" in body  # raw machine value in the card mono row


def test_detail_renders_cover_and_filmstrip_thumbs(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert f"/media/{corpus.pub}/{corpus.cover_hash}/thumb" in body  # cover
    assert f"/media/{corpus.pub}/{corpus.second_hash}/thumb" in body  # filmstrip plate
    assert "Am Lagerfeuer" in body  # cover caption
    assert (
        f'href="/media/{corpus.pub}/{corpus.second_hash}"' in body
    )  # plate → full gated byte route
    # no raw bytes inlined — only /media/ URLs
    assert "data:image" not in body


# --- projection / per-tier (the leak surface, §9) ---------------------------------


def test_member_never_sees_archivist_only_field_values(corpus: _Corpus) -> None:
    body = _body(corpus, Member(groups=()), corpus.pub)
    assert _STANDORT not in body  # physical_location floored to None → row absent
    assert _CUSTOM_VALUE not in body  # custom floored to () → rows absent
    assert "Standort" not in body


def test_public_never_sees_archivist_only_field_values(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert _STANDORT not in body
    assert _CUSTOM_VALUE not in body


def test_archivist_sees_archivist_only_field_values(corpus: _Corpus) -> None:
    body = _body(corpus, Archivist(), corpus.pub)
    assert _STANDORT in body
    assert _CUSTOM_VALUE in body
    assert "Standort" in body


def test_archivist_only_fields_are_the_only_member_vs_archivist_diff(corpus: _Corpus) -> None:
    # guards against a NEW archivist-only field silently reaching members: the two renders must
    # differ ONLY by the archivist-only values + the archivist chrome (action row, its markers).
    member = _body(corpus, Member(groups=()), corpus.pub)
    archivist = _body(corpus, Archivist(), corpus.pub)
    # both carry the shared reading structure
    for shared in ("Sommerfahrt 1962", "Juli 1962", "F 12", "K. Meyer", "Erste Zeile."):
        assert shared in member
        assert shared in archivist
    # the archivist-only VALUES appear only for the archivist
    assert _STANDORT in archivist and _STANDORT not in member
    assert _CUSTOM_VALUE in archivist and _CUSTOM_VALUE not in member


# --- draft visibility (archivist-only, §9) ----------------------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=())])
def test_draft_is_404_for_non_archivist(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(f"/artikel/{corpus.draft}")
    assert response.status_code == 404
    assert response.content == b""  # byte-identical to a nonexistent ulid


def test_draft_is_200_with_badge_and_actions_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{corpus.draft}")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Entwurf" in body  # ENTWURF badge
    assert "/bearbeiten" in body  # action row present


# --- action row / archivist chrome ------------------------------------------------


def test_member_published_view_carries_no_action_row(corpus: _Corpus) -> None:
    body = _body(corpus, Member(groups=()), corpus.pub)
    assert "c-artikel-aktionen" not in body  # no action row for a member
    assert "/bearbeiten" not in body


def test_member_published_view_has_no_amber_or_red(corpus: _Corpus) -> None:
    # §0/§9: a member published view carries NO draft (amber) or error (red) chrome.
    body = _body(corpus, Member(groups=()), corpus.pub)
    assert "c-badge--entwurf" not in body
    assert "--draft" not in body
    assert "--error" not in body


# --- Bestand + Schlagworte links (the browsing loop) ------------------------------


def test_bestand_breadcrumb_links_into_collection_facet(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert "Fotografien" in body  # leaf collection name
    assert "?bestand=FOTOS" in body  # links into the collection facet


def test_schlagworte_link_into_tag_facet(corpus: _Corpus) -> None:
    body = _body(corpus, Public(), corpus.pub)
    assert "?schlagwort=fahrt" in body
    assert "?schlagwort=sommer" in body


# --- design-gate fixups ------------------------------------------------------------


def test_cover_platte_links_to_full_image(corpus: _Corpus) -> None:
    # LOW-MED: the cover always links its full gated byte route, so a single-media article (no
    # filmstrip) still has a path to the full image.
    body = _body(corpus, Public(), corpus.pub)
    assert f'href="/media/{corpus.pub}/{corpus.cover_hash}"' in body


def test_register_count_says_blatt(corpus: _Corpus) -> None:
    # LOW: the register count matches the blessed mock wording.
    body = _body(corpus, Public(), corpus.pub)
    assert "Blatt 1 / 2" in body


def test_pure_text_record_omits_prosa_so_grid_collapses(corpus: _Corpus) -> None:
    # HOLD: a no-body + no-media record renders NO .l-prosa section — the precondition for the
    # `.l-korpus:not(:has(.l-prosa))` single-column collapse (so the card isn't marooned top-right).
    # The card still renders under the title; no cover, no filmstrip.
    body = _body(corpus, Public(), corpus.textonly)
    assert "Nur Text" in body
    assert "l-korpus" in body
    assert "l-prosa" not in body  # no Beschreibung → collapse selector fires
    assert "l-akte" in body  # the record card is still present
    assert "l-platte" not in body  # no cover frame (no media)
    assert "l-register" not in body  # no filmstrip


def test_media_only_record_keeps_the_two_track_grid(corpus: _Corpus) -> None:
    # the media-only / prose-present states keep .l-prosa, so the collapse does NOT fire — the pub
    # article has a body, so its grid stays two-track (guards the :not(:has) precondition boundary).
    body = _body(corpus, Public(), corpus.pub)
    assert "l-prosa" in body


def test_single_media_record_shows_cover_but_no_filmstrip(corpus: _Corpus) -> None:
    # §1 media-state boundary: exactly ONE sheet → the cover Platte renders (l-platte present, linking
    # its full byte route) but the filmstrip register is omitted (l-register absent — the cover IS the
    # only sheet). The 0-media (textonly) and 2-media (pub) states are pinned elsewhere; this pins the
    # ≤1 boundary that decides `{% if weitere %}`.
    body = _body(corpus, Public(), corpus.single)
    assert "Ein Blatt" in body
    assert "l-platte" in body  # cover frame present
    assert f'href="/media/{corpus.single}/{corpus.single_hash}"' in body  # cover links full image
    assert "l-register" not in body  # no filmstrip for a single sheet
    assert "Blatt 1 /" not in body  # no register count


# --- escaping: free-text values round-trip inert (the leak-surface pin) -------------


def test_markup_bearing_fields_render_escaped(corpus: _Corpus) -> None:
    # The detail template auto-escapes every value (no |safe / mark_safe anywhere). A <script> in the
    # title, body, creator, or a media caption must round-trip as escaped text — never as live markup
    # (stored-XSS closed: an archivist-typed field cannot execute in a reader's browser).
    body = _body(corpus, Public(), corpus.markup)
    # the payloads appear ESCAPED …
    assert "&lt;script&gt;alert(&#x27;body&#x27;)&lt;/script&gt;" in body
    assert "&lt;script&gt;alert(&#x27;titel&#x27;)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=1&gt;" in body  # the caption
    # … and NEVER as executable markup.
    assert "<script>alert" not in body
    assert "<img src=x onerror=1>" not in body


def test_zurueck_default_when_no_return_query(corpus: _Corpus) -> None:
    # no ?zurueck → the return link is a bare "/" (unchanged behavior).
    body = _body(corpus, Public(), corpus.pub)
    assert '<a class="l-zurueck" href="/">' in body


def test_zurueck_round_trips_a_clean_search_query(corpus: _Corpus) -> None:
    # MED: the return link carries the search back (q + facet + page), sanitized through the browse
    # param whitelist and re-serialized (never echoed raw).
    body = _body(
        corpus, Public(), corpus.pub, "?zurueck=q%3Dfahrt%26schlagwort%3Dsommer%26seite%3D2"
    )
    assert "l-zurueck" in body
    for fragment in ("q=fahrt", "schlagwort=sommer", "seite=2"):
        assert fragment in body


def test_zurueck_drops_unknown_and_pane_params(corpus: _Corpus) -> None:
    # the sanitizer whitelists known search params only: an injected artikel= (pane state) or a
    # bogus key must not survive into the return link (no reflection / existence oracle).
    body = _body(
        corpus, Public(), corpus.pub, "?zurueck=q%3Dfahrt%26artikel%3DXYZ%26evil%3D%3Cscript%3E"
    )
    assert "q=fahrt" in body
    assert "artikel=" not in body
    assert "evil" not in body
    assert "script" not in body.lower().split("l-zurueck")[1][:200]


def test_zurueck_malformed_falls_back_to_root(corpus: _Corpus) -> None:
    # a ?zurueck with no recognizable search params → the return link is a bare "/".
    body = _body(corpus, Public(), corpus.pub, "?zurueck=%7Bnot-a-query%7D")
    assert '<a class="l-zurueck" href="/">' in body
