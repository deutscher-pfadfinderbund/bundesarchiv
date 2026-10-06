"""Media manager — reorder / remove / upload + caption round-trip (Part 4.7 Slice D, spec §6.3).

Three structural POST routes plus the caption metadata save:

- ``/medien/verschieben`` — reorder (= re-cover, order is meaning ADR 0015). Structural, non-CAS.
- ``/medien/entfernen`` — two-step no-JS confirm (show → [Ja] removes the ref; the blob stays).
- ``/media/upload`` — multipart, multiple files, named write-once files (ADR 0019), append at
  END; oversize or a name that cleans to nothing → a clean German error not a 500, nothing stored.
  The file persists BEFORE the README references it.
- captions ride the main edit-form save (``save_article``), README round-trip, ``"" → None``.

SECURITY (mutation-tested): every structural route archivist-gated, POST-only → 404 for
Member/Public/anon; the deny tests assert the media tuple is UNCHANGED. The write path is real;
only index + queue seams are stubbed (conftest.py).
"""

import io
import re
import tracemalloc
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.test import override_settings
from PIL import Image
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    Corpus,
    client_as,
    download_hrefs,
    make_article,
    make_collection,
    page_hrefs,
)

from bundesarchiv.app.thumbnails import thumbnail_path
from bundesarchiv.app.web.browse_views import media_tiles
from bundesarchiv.app.web.media_views import media_url, thumbnail_url
from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle, MediaRef
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"
_ADDED_AT = datetime(2017, 6, 26, 6, 6, 40, tzinfo=UTC)


class _MediaCorpus:
    """An archive whose one DRAFT article carries two media blobs (a cover + a second) — the shape
    every route here reorders, removes from and re-captions. Built on ``make_corpus`` rather than
    the standard ``corpus``: that shape is frozen and holds no media."""

    def __init__(self, corpus: Corpus) -> None:
        self.store = corpus.store
        self.articles = corpus.articles
        corpus.add_collection(
            make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
        )
        # store two real blobs so the README may reference them (repo refuses an unstored ref)
        self.ref_a = self.articles.add_media(
            _ULID, "cover.jpg", io.BytesIO(b"cover-bytes"), "image/jpeg", "Titelbild"
        )
        self.ref_b = self.articles.add_media(
            _ULID, "zweite.jpg", io.BytesIO(b"second-bytes"), "image/jpeg", None
        )
        self.version = corpus.add_article(
            make_article(
                _ULID,
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                title="Lagerchronik",
                media_type="Foto(s)",
                media=(self.ref_a, self.ref_b),
                added_at=_ADDED_AT,
            )
        )

    def media(self) -> tuple[MediaRef, ...]:
        return self.articles.load(_ULID).article.media


@pytest.fixture
def corpus(make_corpus: Callable[[], Corpus]) -> _MediaCorpus:
    return _MediaCorpus(make_corpus())


def _hashes(corpus: _MediaCorpus) -> list[str]:
    return [m.content_hash for m in corpus.media()]


def _media_drawer_region(body: str) -> str:
    # Mirrors what htmx's hx-select="#media-drawer" extracts client-side from the full-page
    # response: the <section id="media-drawer"> element, start tag through its matching close.
    # (It was a <fieldset> until the form wave turned the seven group drawers into the record card's
    # ruled sections — the region's id, and therefore the swap target, did not change.)
    start = body.index('id="media-drawer"')
    open_tag_start = body.rindex("<section", 0, start)
    end = body.index("</section>", start) + len("</section>")
    return body[open_tag_start:end]


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- reorder (= re-cover) ----------------------------------------------------------


def test_move_down_moves_cover_and_re_covers(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "down"},
    )
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after == [before[1], before[0]]  # swapped → the second entry is now the cover


def test_a_structural_media_edit_keeps_the_date_added(corpus: _MediaCorpus) -> None:
    client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "down"},
    )
    assert corpus.articles.load(_ULID).article.added_at == _ADDED_AT


def test_move_up_at_top_is_noop(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "up"},
    )
    assert _hashes(corpus) == before  # already first → no change


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_move_denied_leaves_order(corpus: _MediaCorpus, viewer: Viewer) -> None:
    before = _hashes(corpus)
    response = client_as(viewer).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "down"},
    )
    assert_denied(response)
    assert _hashes(corpus) == before  # order unchanged


def test_move_get_is_404(corpus: _MediaCorpus) -> None:
    assert_denied(client_as(Archivist()).get(f"/articles/{_ULID}/media/move"))


def test_move_against_deleted_article_is_404(
    corpus: _MediaCorpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _load_gated passes (the article existed at gate time), but the article is hard-deleted before
    # update_article's own load runs — that load must not surface an uncaught 500.
    from bundesarchiv.app.web import catalog_views

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object, object] | None:
        gated = real_gated(request, ulid)
        corpus.articles.hard_delete(_ULID, corpus.articles.load(_ULID).version)
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "down"},
    )
    assert_denied(response)


def test_structural_save_conflict_surfaces_hinweis_not_silent(
    corpus: _MediaCorpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If every structural save attempt loses the race, the archivist must SEE a hinweis (not a
    # silently-unchanged form). Force save_article to always raise Conflict.
    from bundesarchiv.app import articles
    from bundesarchiv.persistence.errors import Conflict

    def _always_conflict(*_a: object, **_k: object) -> None:
        raise Conflict("forced")

    # update_article calls save_article via the app.articles module — patch it at the source.
    monkeypatch.setattr(articles, "save_article", _always_conflict)
    before = _hashes(corpus)
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {"hash": corpus.ref_a.content_hash, "direction": "down"},
    )
    assert response.status_code == 200
    assert "bitte erneut versuchen" in response.content.decode().lower()
    assert _hashes(corpus) == before  # nothing changed


# --- remove (two-step) -------------------------------------------------------------


def test_remove_step1_shows_confirm_without_removing(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/remove", {"remove": corpus.ref_b.content_hash}
    )
    assert response.status_code == 200
    assert "Wirklich entfernen?" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing removed yet


def test_remove_step2_confirmed_removes_ref_blob_stays(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/remove",
        {"remove": corpus.ref_b.content_hash, "confirmed": "1"},
    )
    assert response.status_code == 200
    assert _hashes(corpus) == [corpus.ref_a.content_hash]  # the ref is gone
    # the blob is write-once recoverable — it still exists in the store
    assert corpus.store.exists(corpus.articles.media_key(_ULID, corpus.ref_b))


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_remove_denied_leaves_media(corpus: _MediaCorpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(
        f"/articles/{_ULID}/media/remove",
        {"remove": corpus.ref_b.content_hash, "confirmed": "1"},
    )
    assert_denied(response)
    assert len(corpus.media()) == 2  # nothing removed


def test_member_with_valid_csrf_still_gets_404(corpus: _MediaCorpus) -> None:
    # The real leak-suite concern: an AUTHENTICATED non-archivist can obtain a CSRF token, so CSRF
    # (which floors an anonymous tokenless POST to 403) must not be the only barrier. A Member who
    # clears CSRF must still hit the archivist gate's 404 — no existence oracle, no
    # mutation. Seed the csrf cookie via the DB-free dev switcher GET (prod routes are composed into
    # the dev urlconf), then POST the structural route with a matching token.
    client = client_as(Member(groups=("vorstand",)), enforce_csrf=True)
    with override_settings(
        ROOT_URLCONF="bundesarchiv.app.web.dev_urls",
        MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
    ):
        client.get("/_dev/viewer/")  # DB-free; renders a form → sets the csrf cookie
        token = client.cookies["csrftoken"].value
        response = client.post(
            f"/articles/{_ULID}/media/remove",
            {
                "remove": corpus.ref_b.content_hash,
                "confirmed": "1",
                "csrfmiddlewaretoken": token,
            },
        )
    assert_denied(response)  # the archivist gate, not a 403 and not a leak
    assert len(corpus.media()) == 2  # nothing removed


# --- upload ------------------------------------------------------------------------


def test_upload_appends_at_end_never_displacing_cover(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(Archivist()).post(f"/articles/{_ULID}/media/upload", {"files": upload})
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after[: len(before)] == before  # cover + existing kept, in order
    assert len(after) == len(before) + 1  # appended at the END


def test_upload_the_same_file_again_stores_no_second_file(corpus: _MediaCorpus) -> None:
    files_before = corpus.articles.keys_for(_ULID)
    same = SimpleUploadedFile("cover.jpg", b"cover-bytes", content_type="image/jpeg")
    client_as(Archivist()).post(f"/articles/{_ULID}/media/upload", {"files": same})
    again = corpus.media()[-1]
    assert (again.filename, again.stored_name) == ("cover.jpg", None)
    assert again.content_hash == corpus.ref_a.content_hash
    assert len(corpus.articles.keys_for(_ULID)) == len(files_before) + 1  # + history/<n>.md only


def test_upload_oversize_is_clean_error_not_500(corpus: _MediaCorpus) -> None:
    big = SimpleUploadedFile("gross.jpg", b"x" * 1024, content_type="image/jpeg")
    with override_settings(BUNDESARCHIV_MAX_UPLOAD_BYTES=100):
        response = client_as(Archivist()).post(f"/articles/{_ULID}/media/upload", {"files": big})
    assert response.status_code == 200  # a clean re-render, not a 500
    assert "Datei zu groß" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing attached


def test_a_refused_upload_hands_a_stale_form_its_own_version_back(corpus: _MediaCorpus) -> None:
    # Another archivist saved after this form loaded; the refusal saved nothing of this form's, so
    # the version swapped back into it must not move past that save (the e2e journeys hold the rest).
    archivist = client_as(Archivist())
    other = archivist.post(
        f"/articles/{_ULID}/edit",
        {
            "title": "Anderer",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
            "expected_version": str(corpus.version),
        },
    )
    assert other.status_code == 302
    big = SimpleUploadedFile("gross.jpg", b"x" * 1024, content_type="image/jpeg")
    with override_settings(BUNDESARCHIV_MAX_UPLOAD_BYTES=100):
        response = archivist.post(
            f"/artikel/{_ULID}/medien/hochladen",
            {"files": big, "expected_version": str(corpus.version)},
        )
    assert f'name="expected_version" value="{corpus.version}"' in response.content.decode()


def test_a_media_action_shows_the_typed_captions_and_saves_none(corpus: _MediaCorpus) -> None:
    # With JS the drawer's forms send the typed captions along; the swapped-in rows show them by
    # file, while the move itself writes no caption (ADR 0015). The e2e journeys hold the browser half.
    a, b = corpus.ref_a.content_hash, corpus.ref_b.content_hash
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/media/move",
        {
            "hash": a,
            "direction": "down",
            "expected_version": str(corpus.version),
            f"caption[{a}]": "Getippt A",
            f"caption[{b}]": "Getippt B",
        },
    )
    drawer = _media_drawer_region(response.content.decode())
    assert drawer.index('value="Getippt B"') < drawer.index('value="Getippt A"')
    assert [m.caption for m in corpus.media()] == [None, "Titelbild"]


@pytest.mark.parametrize("name", ["...", "  ", " . "])
def test_upload_a_name_that_cleans_to_nothing_is_refused(corpus: _MediaCorpus, name: str) -> None:
    files_before = corpus.articles.keys_for(_ULID)
    batch = [
        SimpleUploadedFile("gut.jpg", b"good-bytes", content_type="image/jpeg"),
        SimpleUploadedFile(name, b"nameless-bytes", content_type="image/jpeg"),
    ]
    response = client_as(Archivist()).post(f"/articles/{_ULID}/media/upload", {"files": batch})
    assert response.status_code == 200
    assert (
        "Dateiname besteht nur aus Punkten oder Leerzeichen. Bitte die Datei umbenennen."
        in response.content.decode()
    )
    assert len(corpus.media()) == 2  # nothing attached
    assert corpus.articles.keys_for(_ULID) == files_before  # and no file of the batch stored


_BOUNDARY = "grenze"


def _upload_body(tmp_path: Path, filename: str, size: int) -> Path:
    """A multipart request body on disk that uploads ``size`` zero bytes as ``filename``."""
    body = tmp_path / f"body-{filename}"
    with body.open("wb") as out:
        out.write(
            f"--{_BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            "Content-Type: audio/wav\r\n\r\n".encode()
        )
        for _ in range(size // 2**20):
            out.write(bytes(2**20))
        out.write(f"\r\n--{_BOUNDARY}--\r\n".encode())
    return body


def _post_upload(body: Path) -> None:
    """Post ``body`` to the upload view straight from its file, so the test client holds none of
    it."""
    with body.open("rb") as wsgi_input:
        environ: dict[str, Any] = {"wsgi.input": wsgi_input}
        response = client_as(Archivist()).generic(
            "POST",
            f"/articles/{_ULID}/media/upload",
            CONTENT_TYPE=f"multipart/form-data; boundary={_BOUNDARY}",
            CONTENT_LENGTH=str(body.stat().st_size),
            **environ,
        )
    assert response.status_code == 200


def _traced_peak(body: Path) -> int:
    tracemalloc.start()
    try:
        _post_upload(body)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_upload_memory_does_not_grow_with_the_file(corpus: _MediaCorpus, tmp_path: Path) -> None:
    # tech-debt #18. Every file is past FILE_UPLOAD_MAX_MEMORY_SIZE, so Django spools each one. The
    # untraced first upload keeps one-time allocations out of the peaks. The repeat of the large
    # file takes the reuse path, which streams the stored file through the hash.
    small, large = (_upload_body(tmp_path, f"band-{mib}.wav", mib * 2**20) for mib in (4, 32))
    _post_upload(_upload_body(tmp_path, "vorlauf.wav", 4 * 2**20))
    peak_small, peak_large, peak_again = (_traced_peak(body) for body in (small, large, large))
    uploaded = corpus.media()[3:]
    assert [ref.byte_size for ref in uploaded] == [4 * 2**20, 32 * 2**20, 32 * 2**20]
    assert uploaded[2] == uploaded[1]  # the repeat reused the stored file
    assert abs(peak_large - peak_small) < 2**20
    assert abs(peak_again - peak_small) < 2**20


def test_upload_response_carries_per_row_forms_for_every_row(corpus: _MediaCorpus) -> None:
    # fix-wave: the per-row hidden forms (move-<hash>, remove-*-<hash>) must live INSIDE
    # #media-drawer so an htmx swap (hx-select="#media-drawer") delivers fresh forms for the
    # CURRENT row set. The fixture seeds 2 rows, so uploading a third brings the count to 3; check
    # the swapped-in region — not the whole page — carries a move-<hash> form for all 3 rows.
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(Archivist()).post(f"/articles/{_ULID}/media/upload", {"files": upload})
    assert response.status_code == 200
    body = response.content.decode()
    drawer = _media_drawer_region(body)
    hashes_after = _hashes(corpus)
    assert len(hashes_after) == 3  # the new row is really there
    for content_hash in hashes_after:
        assert f'id="move-{content_hash}"' in drawer
    # the worker has not derived the new file's thumbnail yet: its tile is the placeholder
    assert thumbnail_url(_ULID, hashes_after[-1]) not in drawer


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_upload_denied_attaches_nothing(corpus: _MediaCorpus, viewer: Viewer) -> None:
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(viewer).post(f"/articles/{_ULID}/media/upload", {"files": upload})
    assert_denied(response)
    assert len(corpus.media()) == 2  # nothing attached


@pytest.mark.parametrize(
    ("viewer", "ulid", "admitted"),
    [
        (Archivist(), _ULID, True),
        (Public(), _ULID, False),
        (Member(groups=("vorstand",)), _ULID, False),
        (Archivist(), "01KX7YT9E3VX0CP3A5Q49RZMVJ", False),
        (Archivist(), "keine-ulid", False),
    ],
    ids=["archivist", "public", "member", "absent_article", "malformed_ulid"],
)
def test_the_upload_gate_admits_exactly_whom_the_upload_admits(
    corpus: _MediaCorpus, viewer: Viewer, ulid: str, admitted: bool
) -> None:
    """nginx asks this gate before it reads an upload's body (deploy/nginx/nginx.conf)."""
    client = client_as(viewer)
    assert (client.post(f"/articles/{ulid}/media/upload").status_code != 404) is admitted
    gate = client.get(f"/upload-gate/{ulid}", headers={"Sec-Fetch-Site": "same-origin"})
    if admitted:
        assert gate.status_code == 204
    else:
        assert_denied(gate)


@pytest.mark.parametrize(
    ("headers", "admitted"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, True),
        ({"Sec-Fetch-Site": "same-site", "Origin": "http://testserver"}, False),
        ({"Origin": "http://testserver"}, True),
        ({"Origin": "http://andere.testserver"}, False),
        ({"Referer": "http://testserver/articles/"}, True),
        ({"Referer": "http://andere.testserver/"}, False),
        ({}, False),
    ],
    ids=[
        "same_origin",
        "same_site",
        "origin_match",
        "origin_sibling",
        "referer_match",
        "referer_sibling",
        "no_header",
    ],
)
def test_the_upload_gate_admits_only_a_same_origin_request(
    corpus: _MediaCorpus, headers: dict[str, str], admitted: bool
) -> None:
    gate = client_as(Archivist()).get(f"/upload-gate/{_ULID}", headers=headers)
    if admitted:
        assert gate.status_code == 204
    else:
        assert_denied(gate)


def test_only_the_gated_upload_route_takes_a_large_body() -> None:
    """Anyone else's body stays small: nginx buffers a body to disk before the app answers."""
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    server_wide = re.search(r"^    client_max_body_size (\S+);", conf, re.MULTILINE)
    assert server_wide is not None
    assert re.fullmatch(r"\d+m", server_wide[1])
    upload = conf.split("medien/hochladen)$", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 8g;" in upload
    assert "auth_request /_upload_gate;" in upload
    assert conf.count("client_max_body_size 8g;") == 1


def test_the_upload_location_matches_both_spellings_of_the_upload_path() -> None:
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    pattern = re.search(r'location ~ "(\^/[^"]*medien/hochladen\)\$)"', conf)
    assert pattern is not None
    regex = re.compile(pattern[1].replace("(?<", "(?P<"))
    assert regex.match(f"/articles/{_ULID}/media/upload")
    assert regex.match(f"/artikel/{_ULID}/medien/hochladen")
    assert not regex.match(f"/articles/{_ULID}/edit")


def test_the_gate_subrequest_takes_the_uploads_length() -> None:
    """auth_request checks its subrequest against the upload's Content-Length."""
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    gate = conf.split("location = /_upload_gate {", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 0;" in gate


# --- captions ride the metadata save (README round-trip, "" -> None) ---------------


def test_caption_saved_via_edit_form_round_trips(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            "title": "Lagerchronik",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
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


# --- the register renders the cover stamp + zero-state -----------------------------


def test_edit_form_renders_media_register_with_cover_stamp(corpus: _MediaCorpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    # the stamp is a text node; ref_a's caption "Titelbild" is only an input value
    cover_row, rest = body.split("cover.jpg", 1)[1].split("zweite.jpg", 1)
    assert ">Titelbild<" in cover_row
    assert ">Titelbild<" not in rest


def test_a_file_row_shows_a_thumbnail_only_once_the_cache_holds_one(
    corpus: _MediaCorpus, tmp_path: Path
) -> None:
    thumbs = tmp_path / "thumbs"
    cached = thumbnail_path(thumbs, corpus.ref_a.content_hash)
    cached.parent.mkdir()
    Image.new("RGB", (4, 3)).save(cached, format="AVIF")
    with override_settings(BUNDESARCHIV_THUMBNAIL_ROOT=str(thumbs)):
        body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    drawer = _media_drawer_region(body)
    assert thumbnail_url(_ULID, corpus.ref_a.content_hash) in drawer
    assert thumbnail_url(_ULID, corpus.ref_b.content_hash) not in drawer


def test_every_file_row_opens_and_offers_to_save_its_original(corpus: _MediaCorpus) -> None:
    body = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    drawer = _media_drawer_region(body)
    originals = [media_url(_ULID, ref.content_hash) for ref in (corpus.ref_a, corpus.ref_b)]
    assert download_hrefs(drawer) == originals
    assert set(originals) <= set(page_hrefs(drawer))


# --- values-preserved-verbatim: error/conflict re-renders keep typed captions ------


def test_validation_error_re_render_keeps_typed_caption(corpus: _MediaCorpus) -> None:
    # A validation error (empty title) must NOT fall back to the stored caption in the
    # re-rendered media register — the archivist's just-typed caption survives.
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            "title": "",  # invalid -> state F re-render
            "collection_id": "PUB",
            "media_type": "Foto(s)",
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


def test_conflict_re_render_keeps_typed_caption(corpus: _MediaCorpus) -> None:
    archivist = client_as(Archivist())
    winner = archivist.post(
        f"/articles/{_ULID}/edit",
        {
            "title": "Gewinner",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
            "expected_version": str(corpus.version),
        },
    )
    assert winner.status_code == 302
    loser = archivist.post(
        f"/articles/{_ULID}/edit",
        {
            "title": "Verlierer",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
            "expected_version": str(corpus.version),  # stale -> Conflict -> state G
            f"caption[{corpus.ref_a.content_hash}]": "Gelöschte Unterschrift",
        },
    )
    assert loser.status_code == 200
    body = loser.content.decode()
    assert "Inzwischen geändert" in body  # the conflict panel heading
    assert 'value="Gelöschte Unterschrift"' in body


def test_custom_remove_keeps_media_register_and_typed_caption(corpus: _MediaCorpus) -> None:
    # The no-JS custom-row removal re-render must NOT drop the whole Medien drawer.
    response = client_as(Archivist()).post(
        f"/articles/{_ULID}/edit",
        {
            "title": "Lagerchronik",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
            "expected_version": str(corpus.version),
            f"caption[{corpus.ref_a.content_hash}]": "Frisch getippt",
            "custom_key": ["Fotograf"],
            "custom_value": ["Meyer"],
            "custom_remove": "0",
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    drawer = _media_drawer_region(body)
    assert "cover.jpg" in drawer  # the media register is still present
    assert "zweite.jpg" in drawer
    assert 'value="Frisch getippt"' in drawer  # and carries the typed caption
    # nothing saved (removal is a re-render, not a save)
    assert corpus.media() == (corpus.ref_a, corpus.ref_b)


# --- alt text rides the same save as the caption ---------------------------------------


def _edit(corpus: _MediaCorpus, **fields: str) -> int:
    return (
        client_as(Archivist())
        .post(
            f"/articles/{_ULID}/edit",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Foto(s)",
                "expected_version": str(corpus.version),
                **fields,
            },
        )
        .status_code
    )


def test_alt_saved_via_edit_form_round_trips_and_leaves_the_caption(corpus: _MediaCorpus) -> None:
    a, b = corpus.ref_a.content_hash, corpus.ref_b.content_hash
    assert (
        _edit(
            corpus,
            **{
                f"caption[{a}]": "Titelbild",
                f"alt[{a}]": "  Eine Frau am Zelt ",
                f"alt[{b}]": "  ",
            },
        )
        == 302
    )
    by_hash = {m.content_hash: m for m in corpus.media()}
    assert by_hash[a].alt == "Eine Frau am Zelt"  # stripped
    assert by_hash[a].caption == "Titelbild"
    assert by_hash[b].alt is None  # whitespace-only is absent


def test_an_absent_alt_field_leaves_the_stored_alt(corpus: _MediaCorpus) -> None:
    a = corpus.ref_a.content_hash
    assert _edit(corpus, **{f"alt[{a}]": "Erst"}) == 302
    corpus.version += 1
    assert _edit(corpus, **{f"caption[{a}]": "Neu"}) == 302
    assert corpus.media()[0].alt == "Erst"


def test_only_an_image_row_offers_the_alt_field(make_corpus: Callable[[], Corpus]) -> None:
    archive = make_corpus()
    archive.add_collection(
        make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    photo = archive.articles.add_media(_ULID, "a.jpg", io.BytesIO(b"jpg"), "image/jpeg")
    pdf = archive.articles.add_media(_ULID, "b.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")
    archive.add_article(
        make_article(
            _ULID,
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            media=(photo, pdf),
            added_at=_ADDED_AT,
        )
    )
    drawer = _media_drawer_region(
        client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    )
    assert re.findall(r'name="alt\[([0-9a-f]+)\]"', drawer) == [photo.content_hash]
    assert "Für Menschen, die das Bild nicht sehen." in drawer


def _pdf_article(
    make_corpus: Callable[[], Corpus], alt: str | None = None
) -> tuple[Corpus, MediaRef]:
    archive = make_corpus()
    archive.add_collection(
        make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    pdf = replace(
        archive.articles.add_media(_ULID, "b.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf"),
        alt=alt,
    )
    archive.add_article(
        make_article(
            _ULID,
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            title="Lagerchronik",
            media_type="Foto(s)",
            media=(pdf,),
            added_at=_ADDED_AT,
        )
    )
    return archive, pdf


def test_a_forged_alt_for_a_non_image_stores_nothing(make_corpus: Callable[[], Corpus]) -> None:
    archive, pdf = _pdf_article(make_corpus)
    corpus = _MediaCorpus.__new__(_MediaCorpus)
    corpus.articles, corpus.version = archive.articles, 1
    assert _edit(corpus, **{f"alt[{pdf.content_hash}]": "Eingeschmuggelt"}) == 302
    assert corpus.media()[0].alt is None


def test_a_stored_alt_on_a_non_image_is_never_rendered(make_corpus: Callable[[], Corpus]) -> None:
    _pdf_article(make_corpus, alt="Versteckt")
    client = client_as(Archivist())
    assert "Versteckt" not in client.get(f"/articles/{_ULID}").content.decode()
    assert "Versteckt" not in client.get(f"/articles/{_ULID}/edit").content.decode()


def test_an_alt_is_one_line(corpus: _MediaCorpus) -> None:
    a = corpus.ref_a.content_hash
    assert _edit(corpus, **{f"alt[{a}]": "eins\r\nzwei\x85drei\u2028vier"}) == 302
    assert corpus.media()[0].alt == "eins zwei drei vier"


def test_blank_values_are_absent_and_a_save_without_edits_changes_nothing(
    make_corpus: Callable[[], Corpus],
) -> None:
    archive = make_corpus()
    archive.add_collection(
        make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    ref = replace(
        archive.articles.add_media(_ULID, "a.jpg", io.BytesIO(b"jpg"), "image/jpeg"),
        alt="  ",
        caption=" ",
    )
    version = archive.add_article(
        make_article(
            _ULID,
            collection_id="PUB",
            lifecycle=Lifecycle.DRAFT,
            title="Lagerchronik",
            media_type="Foto(s)",
            media=(ref,),
            added_at=_ADDED_AT,
        )
    )
    edit = client_as(Archivist()).get(f"/articles/{_ULID}/edit").content.decode()
    assert re.search(r'name="alt\[[0-9a-f]+\]" value=""', edit)
    corpus = _MediaCorpus.__new__(_MediaCorpus)
    corpus.articles, corpus.version = archive.articles, version
    key = ref.content_hash
    assert _edit(corpus, **{f"alt[{key}]": "", f"caption[{key}]": ""}) == 302
    assert corpus.media() == (ref,)


def test_a_non_images_tile_never_carries_a_stored_alt(make_corpus: Callable[[], Corpus]) -> None:
    _, pdf = _pdf_article(make_corpus, alt="Versteckt")
    assert [t.alt for t in media_tiles(_ULID, (pdf,))] == ["b.pdf"]
