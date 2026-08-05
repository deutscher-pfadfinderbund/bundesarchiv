"""HTMX enhancement endpoints (Part 4.7 Slice E, spec §5).

Two archivist-gated GET partials the edit form's HTMX layer swaps in (the no-JS baseline renders the
same content server-side and is unchanged):

- ``/artikel/<ulid>/dokumenttypen?medienart=`` → the Dokumenttyp option list for one Medienart.
- ``/artikel/<ulid>/datierung-echo?date=`` → the human-German EDTF echo line.

Both are archivist-gated via _load_gated → 404 for Member/Public/anon/malformed/absent,
and must NEVER render partial content for a non-archivist (content-absence asserts — they join the
4.10 leak suite). Pure transforms; no mutation. Plus the state-H index-lag hinweis on the save path.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-catalog-htmx-key"
_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


class _Corpus:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        self.version = ArticleRepository(self.store).save(
            Article(
                ulid=_ULID,
                title="Lagerchronik",
                collection_id="PUB",
                lifecycle=Lifecycle.DRAFT,
                media_type="Fotografie",
            ),
            0,
        )


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


_NON_ARCHIVISTS = [Public(), Member(groups=("vorstand",))]


# --- /dokumenttypen ----------------------------------------------------------------


def test_dokumenttypen_returns_options_for_media_type(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(
            f"/artikel/{_ULID}/dokumenttypen?medienart=Fotografie"
        )
    assert response.status_code == 200
    assert "Porträt" in response.content.decode()  # a Fotografie Dokumenttyp


def test_dokumenttypen_unknown_media_type_yields_only_empty_option(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(
            f"/artikel/{_ULID}/dokumenttypen?medienart=gibtsnicht"
        )
    assert response.status_code == 200
    assert "kein Dokumenttyp" in response.content.decode()


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_dokumenttypen_denied_is_404_never_content(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(f"/artikel/{_ULID}/dokumenttypen?medienart=Fotografie")
    assert response.status_code == 404
    assert b"Portr" not in response.content  # no partial content leaked


def test_dokumenttypen_post_is_404(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        assert (
            _client_as(Archivist())
            .post(f"/artikel/{_ULID}/dokumenttypen", {"medienart": "Fotografie"})
            .status_code
            == 404
        )


# --- /datierung-echo ---------------------------------------------------------------


def test_datierung_echo_renders_german(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_ULID}/datierung-echo?date=1962")
    assert response.status_code == 200
    assert "1962" in response.content.decode()


def test_datierung_echo_decade(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_ULID}/datierung-echo?date=197X")
    assert "1970er" in response.content.decode()


def test_datierung_echo_invalid_is_empty(corpus: _Corpus) -> None:
    # a bad value yields an EMPTY echo (no error surface while typing, spec §5). The wrapper span
    # stays present (a stable HTMX swap target) but carries no echo text.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(f"/artikel/{_ULID}/datierung-echo?date=unsinn")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'id="datierung-echo"' in body  # the swap target is present
    assert "unsinn" not in body  # but no echo rendered for the bad value


@pytest.mark.parametrize("viewer", _NON_ARCHIVISTS)
def test_datierung_echo_denied_is_404_never_content(corpus: _Corpus, viewer: Viewer) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get(f"/artikel/{_ULID}/datierung-echo?date=1962")
    assert response.status_code == 404
    assert b"1962" not in response.content  # no echo leaked


def test_datierung_echo_post_is_404(corpus: _Corpus) -> None:
    # GET-only (a pure transform); a POST must not reach it.
    with override_settings(**_settings(corpus)):
        assert (
            _client_as(Archivist())
            .post(f"/artikel/{_ULID}/datierung-echo", {"date": "1962"})
            .status_code
            == 404
        )


@pytest.mark.parametrize(
    "path",
    [
        "/artikel/not-a-ulid/dokumenttypen?medienart=Fotografie",
        "/artikel/01BX5ZZKBKACTAV9WEVGEMMVRZ/datierung-echo?date=1962",  # well-formed absent
    ],
)
def test_htmx_endpoints_malformed_or_absent_ulid_is_404(corpus: _Corpus, path: str) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get(path)
    assert response.status_code == 404


# --- HTMX save path (no-JS baseline unchanged) --------------------------------------


def test_htmx_save_success_sends_hx_redirect(corpus: _Corpus) -> None:
    # An HTMX save (HX-Request header) that succeeds returns 204 + HX-Redirect (htmx navigates), not
    # a 302 — the destination is identical to the no-JS path, only the mechanism differs.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
            },
            HTTP_HX_REQUEST="true",
        )
    assert response.status_code == 204
    assert response["HX-Redirect"] == f"/artikel/{_ULID}"


def test_no_js_save_success_still_302(corpus: _Corpus) -> None:
    # The no-JS baseline is unchanged: a plain POST (no HX-Request) still 302s.
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
            },
        )
    assert response.status_code == 302
    assert response["Location"] == f"/artikel/{_ULID}"


# --- state H: index-lag hinweis on the save path -----------------------------------


def test_save_with_index_lag_shows_hinweis(
    corpus: _Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the synchronous index update fails (ADR 0014), the canonical write stands and the view
    # must show the quiet "Gespeichert. Die Suche zeigt die Änderung in Kürze." hinweis (state H).
    # This is a no-JS path too, so it re-renders (not a redirect) carrying the hinweis.
    from bundesarchiv.app import articles

    monkeypatch.setattr(
        articles, "index_article", lambda *a, **k: (_ for _ in ()).throw(Exception())
    )
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            f"/artikel/{_ULID}/bearbeiten",
            {
                "title": "Lagerchronik",
                "collection_id": "PUB",
                "media_type": "Fotografie",
                "expected_version": str(corpus.version),
            },
        )
    assert response.status_code == 200  # re-render carrying the hinweis, not a 302
    assert "Die Suche zeigt die Änderung in Kürze." in response.content.decode()
    # the canonical write still stood (version bumped)
    assert ArticleRepository(corpus.store).load(_ULID).version == corpus.version + 1
