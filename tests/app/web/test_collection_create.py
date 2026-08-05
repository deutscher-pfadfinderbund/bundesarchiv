"""The 4.8 create-Bestand form (`/bestand/neu`, `collection_create`).

Archivist-gated both methods (plain 404 otherwise, nothing created). GET renders the
minimal form (Name + Eltern-Bestand + Sichtbarkeit); POST validates (Name required, parent must be a
real collection or the empty top-level option, GROUPS-iff), creates the Collection, and 302s to the
workbench. Setting audience at creation is safe (a fresh collection is empty). Reuses the 4.7 form
grammar wholesale.

Pure request-handling against a local FS store — no Postgres for the gate/render tests; the create
path indexes, so those are django_db.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository

_DEV_KEY = "test-bestand-neu-key"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    store = LocalFsObjectStore(tmp_path / "canonical")
    collections = CollectionRepository(store)
    collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
    collections.save(Collection("FOTOS", "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
    return tmp_path / "canonical"


def _settings(root: Path) -> dict[str, object]:
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": _DEV_KEY,
        "BUNDESARCHIV_CANONICAL_ROOT": str(root),
    }


def _client_as(viewer: Viewer | None) -> Client:
    client = Client()
    if viewer is not None:
        signer = signing.TimestampSigner(key=_DEV_KEY, salt=_DEV_VIEWER_SALT)
        client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def _collections(root: Path) -> tuple[Collection, ...]:
    return CollectionRepository(LocalFsObjectStore(root)).load_all()


# --- archivist gate + 404 discipline ----------------------------------------------


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=())])
@pytest.mark.parametrize("method", ["get", "post"])
def test_non_archivist_gets_404(root: Path, viewer: Viewer | None, method: str) -> None:
    with override_settings(**_settings(root)):
        response = getattr(_client_as(viewer), method)("/bestand/neu")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_creates_nothing(root: Path) -> None:
    before = {c.ulid for c in _collections(root)}
    with override_settings(**_settings(root)):
        _client_as(Public()).post("/bestand/neu", {"name": "Heimlich", "parent_id": ""})
    assert {c.ulid for c in _collections(root)} == before  # nothing created


# --- GET renders the form ---------------------------------------------------------


def test_get_renders_form_with_parent_and_sichtbarkeit(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get("/bestand/neu").content.decode()
    assert "Neuer Bestand" in body
    assert 'name="name"' in body  # Name field
    assert 'name="parent_id"' in body  # Eltern-Bestand select
    assert "Fotografien" in body  # an existing collection is an option
    assert "Vom Bestand erben" in body  # the Sichtbarkeit inherit default
    assert "Öffentlich" in body


# --- POST creates -----------------------------------------------------------------


@pytest.mark.django_db
def test_post_creates_top_level_and_lands_on_catalog_form(root: Path) -> None:
    # BLOCKER 2: create → land on /artikel/neu with the new Bestand pre-selected + a success hinweis
    # (create→catalog is one flow).
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            "/bestand/neu", {"name": "Karten", "parent_id": "", "sichtbarkeit": ""}
        )
    assert response.status_code == 302
    created = [c for c in _collections(root) if c.name == "Karten"]
    assert len(created) == 1
    assert created[0].parent_id is None
    assert created[0].audience is None  # inherit
    # lands on the create-article form, pre-selecting the new Bestand + carrying its name
    location = response["Location"]
    assert location.startswith("/artikel/neu?")
    assert f"bestand={created[0].ulid}" in location
    assert "angelegt=Karten" in location


@pytest.mark.django_db
def test_catalog_form_preselects_bestand_and_shows_hinweis(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = (
            _client_as(Archivist())
            .get("/artikel/neu?bestand=FOTOS&angelegt=Fotografien")
            .content.decode()
        )
    assert 'value="FOTOS" selected' in body  # the Bestand pre-selected in the collection select
    assert "Bestand „Fotografien“ angelegt." in body  # the success status line


@pytest.mark.django_db
def test_catalog_form_ignores_a_bogus_preselect(root: Path) -> None:
    # a ?bestand outside the real set is ignored (no oracle) — no REAL collection is pre-selected
    # (the empty placeholder stays selected, as when no ?bestand is given at all).
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get("/artikel/neu?bestand=NOSUCH").content.decode()
    assert 'value="FOTOS" selected' not in body
    assert 'value="" selected' in body  # the placeholder is the selected option


@pytest.mark.django_db
def test_post_creates_under_parent_with_members_audience(root: Path) -> None:
    with override_settings(**_settings(root)):
        _client_as(Archivist()).post(
            "/bestand/neu",
            {"name": "Interna", "parent_id": "FOTOS", "sichtbarkeit": "members"},
        )
    created = [c for c in _collections(root) if c.name == "Interna"]
    assert len(created) == 1
    assert created[0].parent_id == "FOTOS"
    assert created[0].audience == Audience(AudienceTier.MEMBERS)


@pytest.mark.django_db
def test_post_creates_groups_audience_with_gruppen(root: Path) -> None:
    with override_settings(**_settings(root)):
        _client_as(Archivist()).post(
            "/bestand/neu",
            {
                "name": "Vorstand",
                "parent_id": "",
                "sichtbarkeit": "groups",
                "gruppen": "vorstand, archiv",
            },
        )
    created = [c for c in _collections(root) if c.name == "Vorstand"]
    assert created[0].audience == Audience(AudienceTier.GROUPS, groups=("vorstand", "archiv"))


# --- validation -------------------------------------------------------------------


@pytest.mark.django_db
def test_post_blank_name_re_renders_with_error_and_creates_nothing(root: Path) -> None:
    before = {c.ulid for c in _collections(root)}
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post("/bestand/neu", {"name": "", "parent_id": ""})
    assert response.status_code == 200  # re-render, not redirect
    assert "Name ist erforderlich." in response.content.decode()
    assert {c.ulid for c in _collections(root)} == before  # nothing created


@pytest.mark.django_db
def test_post_groups_without_gruppen_re_renders_with_error(root: Path) -> None:
    before = {c.ulid for c in _collections(root)}
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            "/bestand/neu",
            {"name": "Leer", "parent_id": "", "sichtbarkeit": "groups", "gruppen": ""},
        )
    assert response.status_code == 200
    assert "Gruppe" in response.content.decode()  # a groups-required error
    assert {c.ulid for c in _collections(root)} == before


@pytest.mark.django_db
def test_post_unknown_parent_re_renders_and_creates_nothing(root: Path) -> None:
    # a parent_id outside the real collection set is refused (validated against the actual set — no
    # oracle) — nothing created.
    before = {c.ulid for c in _collections(root)}
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            "/bestand/neu", {"name": "Waise", "parent_id": "NOSUCH"}
        )
    assert response.status_code == 200
    assert {c.ulid for c in _collections(root)} == before
