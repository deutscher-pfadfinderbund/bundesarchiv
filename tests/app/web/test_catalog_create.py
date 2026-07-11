"""The create step ``/artikel/neu`` (Part 4.7 Slice A, spec §2).

GET renders the minimal create form (Titel + Bestand); POST creates a DRAFT via ``create_article``
and 302s to ``/artikel/<ulid>/bearbeiten``. Both methods are archivist-gated: a Member / Public /
anonymous request gets the media route's byte-identical 404 (existence-hiding — the cataloging entry
point must not be discoverable). Validation state B re-renders the form with the verbatim error and
preserved values, no create.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.http.response import HttpResponseBase
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-catalog-create-key"


class _Corpus:
    """A tiny FS-store archive with two collections to file into."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        collections = CollectionRepository(self.store)
        collections.save(Collection("ROOT", "Wurzel", None), 0)
        collections.save(Collection("PUB", "Öffentlich", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
        collections.save(Collection("MEM", "Mitglieder", "ROOT", Audience(AudienceTier.MEMBERS)), 0)


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


# --- GET: the create form ----------------------------------------------------------


def test_create_form_renders_for_archivist(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).get("/artikel/neu")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Neuer Artikel" in body
    assert 'name="title"' in body
    assert 'name="collection_id"' in body
    # the Bestand options list the collections by name
    assert "Öffentlich" in body
    assert "Mitglieder" in body
    # autofocus lands on Titel (spec §5/§8)
    assert "autofocus" in body
    # the form stylesheet is linked (loaded wherever components.css is, spec §4/§6)
    assert '<link rel="stylesheet" href="/static/forms.css">' in body


def test_forms_css_is_served(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        served = _client_as(Archivist()).get("/static/forms.css")
    assert served.status_code == 200
    assert served["Content-Type"] == "text/css"


# --- GET/POST: archivist gate (both methods) --------------------------------------


@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_create_get_is_byte_identical_404_for_non_archivist(
    corpus: _Corpus, viewer: Viewer
) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).get("/artikel/neu")
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()


@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_create_post_is_byte_identical_404_for_non_archivist(
    corpus: _Corpus, viewer: Viewer
) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(viewer).post("/artikel/neu", {"title": "X", "collection_id": "PUB"})
    assert response.status_code == 404
    assert _404_shape(response) == _media_404_shape()
    # nothing was created
    assert list(ArticleRepository(corpus.store).list_ulids()) == []


# --- POST: create + redirect -------------------------------------------------------


def test_create_post_creates_draft_and_redirects_to_edit(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/neu", {"title": "Wanderfahrt 1962", "collection_id": "PUB"}
        )
    assert response.status_code == 302
    ulids = list(ArticleRepository(corpus.store).list_ulids())
    assert len(ulids) == 1
    assert response["Location"] == f"/artikel/{ulids[0]}/bearbeiten"
    stored = ArticleRepository(corpus.store).load(ulids[0])
    assert stored.article.title == "Wanderfahrt 1962"
    assert stored.article.collection_id == "PUB"


def test_create_post_missing_title_re_renders_state_b(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/neu", {"title": "", "collection_id": "PUB"}
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    # the chosen Bestand is preserved
    assert list(ArticleRepository(corpus.store).list_ulids()) == []


def test_create_post_missing_collection_re_renders_state_b(corpus: _Corpus) -> None:
    with override_settings(**_settings(corpus)):
        response = _client_as(Archivist()).post(
            "/artikel/neu", {"title": "Wanderfahrt", "collection_id": ""}
        )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bitte einen Bestand wählen." in body
    # the typed title is preserved
    assert "Wanderfahrt" in body
    assert list(ArticleRepository(corpus.store).list_ulids()) == []
