"""Media manager — reorder / remove / upload + caption round-trip (Part 4.7 Slice D, spec §6.3).

Three structural POST routes plus the caption metadata save:

- ``/medien/verschieben`` — reorder (= re-cover, order is meaning ADR 0015). Structural, non-CAS.
- ``/medien/entfernen`` — two-step no-JS confirm (show → [Ja] removes the ref; the blob stays).
- ``/medien/hochladen`` — multipart, multiple files, named write-once files (ADR 0019), append at
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.test import override_settings
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_article, make_collection

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


def _medien_drawer_region(body: str) -> str:
    # Mirrors what htmx's hx-select="#medien-drawer" extracts client-side from the full-page
    # response: the <section id="medien-drawer"> element, start tag through its matching close.
    # (It was a <fieldset> until the form wave turned the seven group drawers into the record card's
    # ruled sections — the region's id, and therefore the swap target, did not change.)
    start = body.index('id="medien-drawer"')
    open_tag_start = body.rindex("<section", 0, start)
    end = body.index("</section>", start) + len("</section>")
    return body[open_tag_start:end]


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- reorder (= re-cover) ----------------------------------------------------------


def test_verschieben_runter_moves_cover_and_re_covers(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
    )
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after == [before[1], before[0]]  # swapped → the second entry is now the cover


def test_a_structural_media_edit_keeps_the_date_added(corpus: _MediaCorpus) -> None:
    client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
    )
    assert corpus.articles.load(_ULID).article.added_at == _ADDED_AT


def test_verschieben_hoch_at_top_is_noop(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "hoch"},
    )
    assert _hashes(corpus) == before  # already first → no change


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_verschieben_denied_leaves_order(corpus: _MediaCorpus, viewer: Viewer) -> None:
    before = _hashes(corpus)
    response = client_as(viewer).post(
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
    )
    assert_denied(response)
    assert _hashes(corpus) == before  # order unchanged


def test_verschieben_get_is_404(corpus: _MediaCorpus) -> None:
    assert_denied(client_as(Archivist()).get(f"/artikel/{_ULID}/medien/verschieben"))


def test_verschieben_against_deleted_article_is_404(
    corpus: _MediaCorpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # _load_gated passes (the article existed at gate time), but the article is hard-deleted before
    # update_article's own load runs — that load must not surface an uncaught 500.
    from bundesarchiv.app.web import catalog_views

    real_gated = catalog_views._load_gated

    def _delete_then_gate(request: HttpRequest, ulid: str) -> tuple[object, object, object] | None:
        gated = real_gated(request, ulid)
        corpus.articles.hard_delete(_ULID)
        return gated

    monkeypatch.setattr(catalog_views, "_load_gated", _delete_then_gate)
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
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
        f"/artikel/{_ULID}/medien/verschieben",
        {"hash": corpus.ref_a.content_hash, "richtung": "runter"},
    )
    assert response.status_code == 200
    assert "bitte erneut versuchen" in response.content.decode().lower()
    assert _hashes(corpus) == before  # nothing changed


# --- remove (two-step) -------------------------------------------------------------


def test_entfernen_step1_shows_confirm_without_removing(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/entfernen", {"entfernen": corpus.ref_b.content_hash}
    )
    assert response.status_code == 200
    assert "Wirklich entfernen?" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing removed yet


def test_entfernen_step2_confirmed_removes_ref_blob_stays(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/entfernen",
        {"entfernen": corpus.ref_b.content_hash, "bestaetigt": "1"},
    )
    assert response.status_code == 200
    assert _hashes(corpus) == [corpus.ref_a.content_hash]  # the ref is gone
    # the blob is write-once recoverable — it still exists in the store
    assert corpus.store.exists(corpus.articles.media_key(_ULID, corpus.ref_b))


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_entfernen_denied_leaves_media(corpus: _MediaCorpus, viewer: Viewer) -> None:
    response = client_as(viewer).post(
        f"/artikel/{_ULID}/medien/entfernen",
        {"entfernen": corpus.ref_b.content_hash, "bestaetigt": "1"},
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
            f"/artikel/{_ULID}/medien/entfernen",
            {
                "entfernen": corpus.ref_b.content_hash,
                "bestaetigt": "1",
                "csrfmiddlewaretoken": token,
            },
        )
    assert_denied(response)  # the archivist gate, not a 403 and not a leak
    assert len(corpus.media()) == 2  # nothing removed


# --- upload ------------------------------------------------------------------------


def test_hochladen_appends_at_end_never_displacing_cover(corpus: _MediaCorpus) -> None:
    before = _hashes(corpus)
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/medien/hochladen", {"dateien": upload}
    )
    assert response.status_code == 200
    after = _hashes(corpus)
    assert after[: len(before)] == before  # cover + existing kept, in order
    assert len(after) == len(before) + 1  # appended at the END


def test_hochladen_the_same_file_again_stores_no_second_file(corpus: _MediaCorpus) -> None:
    files_before = corpus.articles.keys_for(_ULID)
    same = SimpleUploadedFile("cover.jpg", b"cover-bytes", content_type="image/jpeg")
    client_as(Archivist()).post(f"/artikel/{_ULID}/medien/hochladen", {"dateien": same})
    again = corpus.media()[-1]
    assert (again.filename, again.stored_name) == ("cover.jpg", None)
    assert again.content_hash == corpus.ref_a.content_hash
    assert len(corpus.articles.keys_for(_ULID)) == len(files_before) + 1  # + history/<n>.md only


def test_hochladen_oversize_is_clean_error_not_500(corpus: _MediaCorpus) -> None:
    big = SimpleUploadedFile("gross.jpg", b"x" * 1024, content_type="image/jpeg")
    with override_settings(BUNDESARCHIV_MAX_UPLOAD_BYTES=100):
        response = client_as(Archivist()).post(
            f"/artikel/{_ULID}/medien/hochladen", {"dateien": big}
        )
    assert response.status_code == 200  # a clean re-render, not a 500
    assert "Datei zu groß" in response.content.decode()
    assert len(corpus.media()) == 2  # nothing attached


@pytest.mark.parametrize("name", ["...", "  ", " . "])
def test_hochladen_a_name_that_cleans_to_nothing_is_refused(
    corpus: _MediaCorpus, name: str
) -> None:
    files_before = corpus.articles.keys_for(_ULID)
    batch = [
        SimpleUploadedFile("gut.jpg", b"good-bytes", content_type="image/jpeg"),
        SimpleUploadedFile(name, b"nameless-bytes", content_type="image/jpeg"),
    ]
    response = client_as(Archivist()).post(f"/artikel/{_ULID}/medien/hochladen", {"dateien": batch})
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
            f'Content-Disposition: form-data; name="dateien"; filename="{filename}"\r\n'
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
            f"/artikel/{_ULID}/medien/hochladen",
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


def test_hochladen_memory_does_not_grow_with_the_file(corpus: _MediaCorpus, tmp_path: Path) -> None:
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


def test_hochladen_response_carries_per_row_forms_for_every_row(corpus: _MediaCorpus) -> None:
    # fix-wave: the per-row hidden forms (verschieben-<hash>, entfernen-*-<hash>) must live INSIDE
    # #medien-drawer so an htmx swap (hx-select="#medien-drawer") delivers fresh forms for the
    # CURRENT row set. The fixture seeds 2 rows, so uploading a third brings the count to 3; check
    # the swapped-in region — not the whole page — carries a verschieben-<hash> form for all 3 rows.
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(Archivist()).post(
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
def test_hochladen_denied_attaches_nothing(corpus: _MediaCorpus, viewer: Viewer) -> None:
    upload = SimpleUploadedFile("dritte.jpg", b"third-bytes", content_type="image/jpeg")
    response = client_as(viewer).post(f"/artikel/{_ULID}/medien/hochladen", {"dateien": upload})
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
    assert (client.post(f"/artikel/{ulid}/medien/hochladen").status_code != 404) is admitted
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
        ({"Referer": "http://testserver/artikel/"}, True),
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
    upload = conf.split("/medien/hochladen$", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 8g;" in upload
    assert "auth_request /_upload_gate;" in upload
    assert conf.count("client_max_body_size 8g;") == 1


def test_the_gate_subrequest_takes_the_uploads_length() -> None:
    """auth_request checks its subrequest against the upload's Content-Length."""
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    gate = conf.split("location = /_upload_gate {", 1)[1].split("}", 1)[0]
    assert "client_max_body_size 0;" in gate


# --- captions ride the metadata save (README round-trip, "" -> None) ---------------


def test_caption_saved_via_edit_form_round_trips(corpus: _MediaCorpus) -> None:
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
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
    body = client_as(Archivist()).get(f"/artikel/{_ULID}/bearbeiten").content.decode()
    assert f"/media/{_ULID}/{corpus.ref_a.content_hash}/thumb" in body  # gated thumb URL
    # the stamp is a text node; ref_a's caption "Titelbild" is only an input value
    cover_row, rest = body.split("cover.jpg", 1)[1].split("zweite.jpg", 1)
    assert ">Titelbild<" in cover_row
    assert ">Titelbild<" not in rest


# --- values-preserved-verbatim: error/conflict re-renders keep typed captions ------


def test_validation_error_re_render_keeps_typed_caption(corpus: _MediaCorpus) -> None:
    # A validation error (empty title) must NOT fall back to the stored caption in the
    # re-rendered media register — the archivist's just-typed caption survives.
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
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
        f"/artikel/{_ULID}/bearbeiten",
        {
            "title": "Gewinner",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
            "expected_version": str(corpus.version),
        },
    )
    assert winner.status_code == 302
    loser = archivist.post(
        f"/artikel/{_ULID}/bearbeiten",
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


def test_custom_entfernen_keeps_media_register_and_typed_caption(corpus: _MediaCorpus) -> None:
    # The no-JS custom-row removal re-render must NOT drop the whole Medien drawer.
    response = client_as(Archivist()).post(
        f"/artikel/{_ULID}/bearbeiten",
        {
            "title": "Lagerchronik",
            "collection_id": "PUB",
            "media_type": "Foto(s)",
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
