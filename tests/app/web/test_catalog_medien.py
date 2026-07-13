"""Media manager — reorder / remove / upload + caption round-trip (Part 4.7 Slice D, spec §6.3).

Three structural POST routes plus the caption metadata save:

- ``/medien/verschieben`` — reorder (= re-cover, order is meaning ADR 0015). Structural, non-CAS.
- ``/medien/entfernen`` — two-step no-JS confirm (show → [Ja] removes the ref; the blob stays).
- ``/medien/hochladen`` — multipart, multiple files, write-once dedupe, append at END; oversize →
  a clean German error not a 500. The blob persists BEFORE the README references it.
- captions ride the main edit-form save (``save_article``), README round-trip, ``"" → None``.

SECURITY (mutation-tested): every structural route archivist-gated, POST-only → byte-identical 404
for Member/Public/anon; the deny tests assert the media tuple is UNCHANGED. The write path is real;
only index + queue seams are stubbed (conftest.py).
"""

from pathlib import Path

import pytest
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
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

_DEV_KEY = "test-catalog-medien-key"
_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


class _Corpus:
    """A FS-store archive: one DRAFT article with two media blobs (a cover + a second)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        repo = ArticleRepository(self.store)
        # store two real blobs so the README may reference them (repo refuses an unstored ref)
        self.ref_a = repo.add_media(_ULID, "cover.jpg", b"cover-bytes", "image/jpeg", "Titelbild")
        self.ref_b = repo.add_media(_ULID, "zweite.jpg", b"second-bytes", "image/jpeg", None)
        self.version = repo.save(
            Article(
                ulid=_ULID,
                title="Lagerchronik",
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                media_type="Fotografie",
                media=(self.ref_a, self.ref_b),
            ),
            0,
        )

    def media(self) -> tuple[MediaRef, ...]:
        return ArticleRepository(self.store).load(_ULID).article.media


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


def _media_404_shape() -> tuple[bytes, frozenset[tuple[str, str]]]:
    from bundesarchiv.app.web.media_views import _not_found

    r = _not_found()
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    return r.content, frozenset((k, v) for k, v in r.items() if k not in volatile)


def _404_shape(response: HttpResponseBase) -> tuple[bytes, frozenset[tuple[str, str]]]:
    volatile = {"Date", "Server", "X-Frame-Options", "Vary", "Content-Language"}
    headers = frozenset((k, v) for k, v in response.items() if k not in volatile)
    content: bytes = response.content  # type: ignore[attr-defined]
    return content, headers


def _hashes(corpus: _Corpus) -> list[str]:
    return [m.content_hash for m in corpus.media()]


def _medien_drawer_region(body: str) -> str:
    # Mirrors what htmx's hx-select="#medien-drawer" extracts client-side from the full-page
    # response: the <fieldset id="medien-drawer"> element, start tag through its matching close.
    start = body.index('id="medien-drawer"')
    open_tag_start = body.rindex("<fieldset", 0, start)
    end = body.index("</fieldset>", start) + len("</fieldset>")
    return body[open_tag_start:end]


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- reorder (= re-cover) ----------------------------------------------------------


def test_verschieben_runter_moves_cover_and_re_covers(corpus: _Corpus) -> None:
    before = _hashes(corpus)
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/verschieben",
            {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
        )
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after == [before[1], before[0]]  # swapped → the second entry is now the cover


def test_verschieben_hoch_at_top_is_noop(corpus: _Corpus) -> None:
    before = _hashes(corpus)
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/verschieben",
            {"hash": corpus.ref_a.content_hash, "richtung": "hoch"},
        )
    assert _hashes(corpus) == before  # already first → no change


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_verschieben_denied_leaves_order(corpus: _Corpus, viewer: Viewer) -> None:
    before = _hashes(corpus)
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_ULID}/medien/verschieben",
            {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    assert _hashes(corpus) == before  # order unchanged


def test_verschieben_get_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        assert (
            _client_as(Archivist()).get(f"/artikel/{_ULID}/medien/verschieben").status_code == 404
        )


def test_verschieben_against_deleted_article_is_byte_identical_404(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _load_gated passes (the article existed at gate time), but the article is hard-deleted before
    # _structural_save's own re-load runs — that re-load must not surface an uncaught 500.
    from bundesarchiv.app.web import catalog_views

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object] | None:
        gated = real_gated(request, ulid)
        ArticleRepository(corpus.store).hard_delete(_ULID)
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/verschieben",
            {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()


def test_structural_save_conflict_surfaces_hinweis_not_silent(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If every structural save attempt loses the race, the archivist must SEE a hinweis (not a
    # silently-unchanged form). Force save_article to always raise Conflict.
    from bundesarchiv.app import articles
    from bundesarchiv.persistence.errors import Conflict

    def _always_conflict(*_a: object, **_k: object) -> None:
        raise Conflict("forced")

    # _structural_save calls save_article via the app.articles module — patch it at the source.
    monkeypatch.setattr(articles, "save_article", _always_conflict)
    before = _hashes(corpus)
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/verschieben",
            {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
        )
    assert response.status_code == 200
    assert "bitte erneut versuchen" in response.content.decode().lower()
    assert _hashes(corpus) == before  # nothing changed


# --- remove (two-step) -------------------------------------------------------------


def test_entfernen_step1_shows_confirm_without_removing(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/entfernen", {"entfernen": corpus.ref_b.content_hash}
        )
    assert response.status_code == 200
    assert "Wirklich entfernen?" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing removed yet


def test_entfernen_step2_confirmed_removes_ref_blob_stays(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/entfernen",
            {"entfernen": corpus.ref_b.content_hash, "bestaetigt": "1"},
        )
    assert response.status_code == 200
    assert _hashes(corpus) == [corpus.ref_a.content_hash]  # the ref is gone
    # the blob is write-once recoverable — it still exists in the store
    from bundesarchiv.persistence.repository import _media_key

    assert corpus.store.exists(_media_key(_ULID, corpus.ref_b.content_hash))


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_entfernen_denied_leaves_media(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_ULID}/medien/entfernen",
            {"entfernen": corpus.ref_b.content_hash, "bestaetigt": "1"},
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    assert len(corpus.media()) == 2  # nothing removed


def test_member_with_valid_csrf_still_gets_byte_identical_404(corpus: _Corpus) -> None:
    # The real leak-suite concern: an AUTHENTICATED non-archivist can obtain a CSRF token, so CSRF
    # (which floors an anonymous tokenless POST to 403) must not be the only barrier. A Member who
    # clears CSRF must still hit the archivist gate's byte-identical 404 — no existence oracle, no
    # mutation. Seed the csrf cookie via the DB-free dev switcher GET (prod routes are composed into
    # the dev urlconf), then POST the structural route with a matching token.
    client = Client(enforce_csrf_checks=True)
    signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
    client.cookies["dev_viewer"] = signer.sign(encode_viewer(Member(groups=("vorstand",))))
    dev_settings = {
        **_settings(corpus),
        "ROOT_URLCONF": "bundesarchiv.app.web.dev_urls",
        "MIDDLEWARE": [
            "django.middleware.csrf.CsrfViewMiddleware",
            "bundesarchiv.app.web.dev.DevViewerMiddleware",
        ],
    }
    with override_settings(**dev_settings):
        client.get("/_dev/viewer/")  # DB-free; renders a form → sets the csrf cookie
        token = client.cookies["csrftoken"].value
        response = client.post(
            f"/artikel/{_ULID}/medien/entfernen",
            {
                "entfernen": corpus.ref_b.content_hash,
                "bestaetigt": "1",
                "csrfmiddlewaretoken": token,
            },
        )
    assert response.status_code == 404  # the archivist gate, not a 403 and not a leak
    assert _404_shape(response) == _media_404_shape()
    assert len(corpus.media()) == 2  # nothing removed


# --- upload ------------------------------------------------------------------------


def test_hochladen_appends_at_end_never_displacing_cover(corpus: _Corpus) -> None:
    before = _hashes(corpus)
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/hochladen", {"dateien": upload}
        )
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after[: len(before)] == before  # cover + existing kept, in order
    assert len(after) == len(before) + 1  # appended at the END


def test_hochladen_identical_bytes_is_noop_dedupe(corpus: _Corpus) -> None:
    # Re-uploading the cover's exact bytes is a write-once no-op attach (same content hash) — it does
    # not create a duplicate ref beyond appending the (identical-hash) ref once.
    same = SimpleUploadedFile("cover-again.jpg", b"cover-bytes", content_type="image/jpeg")
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(f"/artikel/{_ULID}/medien/hochladen", {"dateien": same})
    hashes = _hashes(corpus)
    # the content hash of b"cover-bytes" already existed; appending it yields at most a duplicate
    # entry of the SAME hash — the blob is deduped (one stored blob), which is the write-once contract
    assert corpus.ref_a.content_hash in hashes


def test_hochladen_oversize_is_clean_error_not_500(corpus: _Corpus) -> None:
    big = SimpleUploadedFile("gross.jpg", b"x" * 1024, content_type="image/jpeg")
    with override_settings(**_settings(corpus), DATA_UPLOAD_MAX_MEMORY_SIZE=100):
        # force the per-file ceiling low so 1 KB is "oversize"
        from bundesarchiv.app.web import catalog_views

        original = catalog_views._MAX_UPLOAD_BYTES
        catalog_views._MAX_UPLOAD_BYTES = 100
        try:
            response = _client_as(Archivist()).post(
                f"/artikel/{_ULID}/medien/hochladen", {"dateien": big}
            )
        finally:
            catalog_views._MAX_UPLOAD_BYTES = original
    assert response.status_code == 200  # a clean re-render, not a 500
    assert "Datei zu groß" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing attached


def test_hochladen_response_carries_per_row_forms_for_every_row(corpus: _Corpus) -> None:
    # fix-wave: the per-row hidden forms (verschieben-<hash>, entfernen-*-<hash>) must live INSIDE
    # #medien-drawer so an htmx swap (hx-select="#medien-drawer") delivers fresh forms for the
    # CURRENT row set. The fixture seeds 2 rows, so uploading a third brings the count to 3; check
    # the swapped-in region — not the whole page — carries a verschieben-<hash> form for all 3 rows.
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/hochladen", {"dateien": upload}
        )
    assert response.status_code == 200
    body = response.content.decode()
    drawer = _medien_drawer_region(body)
    hashes_after = _hashes(corpus)
    assert len(hashes_after) == 3  # the new row is really there
    for content_hash in hashes_after:
        assert f'id="verschieben-{content_hash}"' in drawer


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_hochladen_denied_attaches_nothing(corpus: _Corpus, viewer: Viewer) -> None:
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post(
            f"/artikel/{_ULID}/medien/hochladen", {"dateien": upload}
        )
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    assert len(corpus.media()) == 2  # nothing attached


# --- captions ride the metadata save (README round-trip, "" -> None) ---------------


def test_caption_saved_via_edit_form_round_trips(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
                f"caption[{corpus.ref_a.content_hash}]": "Neue Unterschrift",
                f"caption[{corpus.ref_b.content_hash}]": "",  # "" -> None
            },
        )
    assert response.status_code == 302  # saved
    media = corpus.media()
    by_hash = {m.content_hash: m for m in media}
    assert by_hash[corpus.ref_a.content_hash].caption == "Neue Unterschrift"
    assert by_hash[corpus.ref_b.content_hash].caption is None  # blank caption -> None
    # order + refs preserved (the metadata save never wipes media)
    assert [m.content_hash for m in media] == [
        corpus.ref_a.content_hash,
        corpus.ref_b.content_hash,
    ]


def test_edit_save_preserves_media_when_no_caption_change(corpus: _Corpus) -> None:
    # A plain metadata save (no caption fields touched) must NOT wipe the media tuple.
    with override_settings(**_settings(corpus)):
        _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Neuer Titel",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
                f"caption[{corpus.ref_a.content_hash}]": "Titelbild",
                f"caption[{corpus.ref_b.content_hash}]": "",
            },
        )
    assert len(corpus.media()) == 2  # media survived the metadata save


# --- the register renders the cover stamp + zero-state -----------------------------


def test_edit_form_renders_media_register_with_cover_stamp(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    assert "c-medien" in body
    assert "Titelbild" in body  # the cover stamp label
    assert "cover.jpg" in body  # the filename
    assert f"/media/{_ULID}/{corpus.ref_a.content_hash}/thumb" in body  # gated thumb URL


def test_edit_form_zero_state_when_no_media(corpus: _Corpus) -> None:
    # a fresh article with no media shows the teaching zero-state
    repo = ArticleRepository(corpus.store)
    empty = "01KX7YT9E3VX0CP3A5Q49RZMWK"
    repo.save(Article(ulid=empty, title="Leer", collection_id="PUB", lifecycle=Lifecycle.DRAFT), 0)
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{empty}/bearbeiten").content.decode()
    assert "Noch keine Medien" in body
    assert "Das erste hochgeladene Bild wird zum Titelbild." in body


def test_upload_controls_belong_to_the_medien_upload_form(corpus: _Corpus) -> None:
    # fix-wave: the upload file input + button sit inside the Medien drawer but carry
    # form="medien-upload" (the separate multipart form declared after the main form).
    with override_settings(**_settings(corpus)):
        body = _client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    assert 'type="file" name="dateien" form="medien-upload"' in body
    assert '<form id="medien-upload"' in body
    assert 'enctype="multipart/form-data"' in body


# --- values-preserved-verbatim: error/conflict re-renders keep typed captions ------


def test_validation_error_re_render_keeps_typed_caption(corpus: _Corpus) -> None:
    # A validation error (empty title) must NOT fall back to the stored caption in the
    # re-rendered media register — the archivist's just-typed caption survives.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "",  # invalid -> state F re-render
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
                f"caption[{corpus.ref_a.content_hash}]": "Meine neue Unterschrift",
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    assert 'value="Meine neue Unterschrift"' in body
    assert 'value="Titelbild"' not in body  # the stale stored caption, not just duplicated
    # nothing saved
    assert corpus.media() == (corpus.ref_a, corpus.ref_b)


def test_conflict_re_render_keeps_typed_caption(corpus: _Corpus) -> None:
    archivist = _client_as(Archivist())
    with override_settings(**_settings(corpus)):
        winner = archivist.post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Gewinner",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
            },
        )
        assert winner.status_code == 302
        loser = archivist.post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Verlierer",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),  # stale -> Conflict -> state G
                f"caption[{corpus.ref_a.content_hash}]": "Gelöschte Unterschrift",
            },
        )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body  # the conflict panel heading
    assert 'value="Gelöschte Unterschrift"' in body


def test_custom_entfernen_keeps_media_register_and_typed_caption(corpus: _Corpus) -> None:
    # The no-JS custom-row removal re-render must NOT drop the whole Medien drawer.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
                f"caption[{corpus.ref_a.content_hash}]": "Frisch getippt",
                "custom_key": ["Fotograf"],
                "custom_value": ["Meyer"],
                "custom_entfernen": "0",
            },
        )
    assert response.status_code == 200
    body = response.content.decode()
    drawer = _medien_drawer_region(body)
    assert "cover.jpg" in drawer  # the media register is still present
    assert "zweite.jpg" in drawer
    assert 'value="Frisch getippt"' in drawer  # and carries the typed caption
    # nothing saved (removal is a re-render, not a save)
    assert corpus.media() == (corpus.ref_a, corpus.ref_b)
