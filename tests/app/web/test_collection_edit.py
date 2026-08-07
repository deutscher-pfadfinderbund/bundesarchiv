"""The 4.8 rename-Bestand form (`/bestand/<ulid>/bearbeiten`, `collection_edit`).

SLIM rename: Name field ONLY. Parent + Sichtbarkeit render as quiet READ-ONLY display rows with one
hint — moving + changing visibility are deferred. Archivist-gated both methods (404 otherwise);
a malformed/absent ulid is likewise a 404. POST saves under CAS and reindexes the subtree
(the name is live in facets on the next render). A renamed Bestand shows its new name in workbench
facets — pinned by a test.
"""

import re
from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-bestand-edit-key"

FOTOS = new_ulid()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    store = LocalFsObjectStore(tmp_path / "canonical")
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
    collections.save(Collection(FOTOS, "Fotografien", "ROOT", Audience(AudienceTier.MEMBERS)), 0)
    articles.save(
        Article(
            ulid=new_ulid(),
            title="Ein Foto",
            collection_id=FOTOS,
            lifecycle=Lifecycle.PUBLISHED,
        ),
        0,
    )
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


def _name_of(root: Path, ulid: str) -> str:
    return CollectionRepository(LocalFsObjectStore(root)).load(ulid).collection.name


# --- archivist gate + 404 discipline ----------------------------------------------


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=())])
@pytest.mark.parametrize("method", ["get", "post"])
def test_non_archivist_gets_404(root: Path, viewer: Viewer | None, method: str) -> None:
    with override_settings(**_settings(root)):
        response = getattr(_client_as(viewer), method)(f"/bestand/{FOTOS}/bearbeiten")
    assert_denied(response)


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_malformed_or_absent_ulid_is_404(root: Path, ulid: str) -> None:
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).get(f"/bestand/{ulid}/bearbeiten")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_leaves_name_unchanged(root: Path) -> None:
    with override_settings(**_settings(root)):
        _client_as(Public()).post(f"/bestand/{FOTOS}/bearbeiten", {"name": "Gehackt"})
    assert _name_of(root, FOTOS) == "Fotografien"  # unchanged


# --- GET renders the rename form (Name editable, parent + Sichtbarkeit read-only) --


def test_get_renders_name_field_and_readonly_rows(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
    assert 'name="name"' in body  # Name is editable
    assert "Fotografien" in body  # current name seeded
    assert "Bundesarchiv" in body  # parent shown read-only (the parent's name)
    assert "Alle Mitglieder" in body  # Sichtbarkeit shown read-only (MEMBERS label)
    assert "Verschieben und Sichtbarkeit ändern folgen später." in body  # the deferred hint
    # parent + Sichtbarkeit are NOT editable controls
    assert 'name="parent_id"' not in body
    assert 'name="sichtbarkeit"' not in body


# --- POST renames -----------------------------------------------------------------


@pytest.mark.django_db
def test_post_renames_and_redirects(root: Path) -> None:
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            f"/bestand/{FOTOS}/bearbeiten", {"name": "Lichtbilder", "expected_version": "1"}
        )
    assert response.status_code == 302
    assert _name_of(root, FOTOS) == "Lichtbilder"


@pytest.mark.django_db
def test_post_blank_name_re_renders_with_error_unchanged(root: Path) -> None:
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            f"/bestand/{FOTOS}/bearbeiten", {"name": "", "expected_version": "1"}
        )
    assert response.status_code == 200
    assert "Name ist erforderlich." in response.content.decode()
    assert _name_of(root, FOTOS) == "Fotografien"  # unchanged


@pytest.mark.django_db
def test_rename_shows_new_name_in_workbench_facets(root: Path) -> None:
    # the reindex path must surface the new name in the collection facet group (the denormalized
    # ancestors reindex + the live name resolution).
    with override_settings(**_settings(root)):
        client = _client_as(Archivist())
        client.post(
            f"/bestand/{FOTOS}/bearbeiten", {"name": "Lichtbilder", "expected_version": "1"}
        )
        body = client.get("/").content.decode()
    assert "Lichtbilder" in body  # the renamed Bestand's new name in the rail's Bestand dropdown
    assert "Fotografien" not in body  # the old name is gone


# --- read-only display grammar (matches the shared 4.7 source strings) --------------


def test_readonly_sichtbarkeit_uses_shared_source_strings(root: Path) -> None:
    # FOTOS is MEMBERS in this fixture → "Alle Mitglieder"; the inherit + groups captions must match
    # the 4.7 source ("Vom Bestand erben", "Gruppe: ") — grammar fixups 5 + 6.
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
    assert "Alle Mitglieder" in body
    assert "Vom Eltern-Bestand erben" not in body  # the old, non-matching inherit string is gone
    assert "Gruppe(n):" not in body  # the old, non-matching groups prefix is gone


# --- racing rename: Conflict → the "Inzwischen geändert" panel (security LOW) --------


def _expected_version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d*)"', body)
    assert match is not None, (
        "GET must seed a hidden expected_version (parity with the article form)"
    )
    return match.group(1)


@pytest.mark.django_db
def test_get_seeds_hidden_expected_version(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
    assert _expected_version_of(body) == "1"  # FOTOS was saved once in the fixture -> v1


@pytest.mark.django_db
def test_stale_expected_version_loses_the_race_and_preserves_input(root: Path) -> None:
    # The genuine race the brief describes: the form is GET'd at v1, a CONCURRENT rename (a second
    # archivist, or this same one in another tab) bumps the store to v2, and the ORIGINAL stale form
    # then POSTs expected_version=1. The CAS check must reject that stale version — a rename that
    # raced another rename must NOT silently win (lost update) — and re-render the "Inzwischen
    # geändert" panel with the winner's name shown and the submitted name preserved.
    with override_settings(**_settings(root)):
        client = _client_as(Archivist())
        get_body = client.get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
        stale_version = _expected_version_of(get_body)
        assert stale_version == "1"

        # a concurrent rename lands first (its own fresh GET+POST at v1), bumping the store to v2
        client.post(
            f"/bestand/{FOTOS}/bearbeiten",
            {"name": "Lichtbilder", "expected_version": stale_version},
        )
        assert _name_of(root, FOTOS) == "Lichtbilder"

        # the ORIGINAL stale form now POSTs, still carrying expected_version=1
        response = client.post(
            f"/bestand/{FOTOS}/bearbeiten",
            {"name": "Gestohlen", "expected_version": stale_version},
        )
    assert response.status_code == 200  # not a 500, and NOT a redirect (no save happened)
    body = response.content.decode()
    assert "Inzwischen geändert" in body  # the conflict panel
    assert "Lichtbilder" in body  # the winner's name is shown
    assert 'value="Gestohlen"' in body  # the just-submitted (losing) name is preserved in the input
    assert _expected_version_of(body) == "2"  # refreshed to the winner's version
    assert (
        _name_of(root, FOTOS) == "Lichtbilder"
    )  # the stale rename never took effect (no lost update)


@pytest.mark.django_db
def test_matching_expected_version_still_saves_and_redirects(root: Path) -> None:
    # Pin: a fresh rename (matching version) still saves and redirects, now that expected_version
    # rides the form.
    with override_settings(**_settings(root)):
        client = _client_as(Archivist())
        get_body = client.get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
        version = _expected_version_of(get_body)
        response = client.post(
            f"/bestand/{FOTOS}/bearbeiten",
            {"name": "Lichtbilder", "expected_version": version},
        )
    assert response.status_code == 302
    assert response["Location"] == f"/?bestand={FOTOS}"
    assert _name_of(root, FOTOS) == "Lichtbilder"


@pytest.mark.django_db
def test_racing_rename_conflict_re_renders_panel_not_500(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A concurrent rename won between GET and POST: the CAS save raises Conflict; the view must
    # re-render the "Inzwischen geändert" panel (200) with a refreshed version — never a 500.
    from bundesarchiv.app.web import collection_views
    from bundesarchiv.persistence.errors import Conflict

    def boom(*_args: object, **_kwargs: object) -> None:
        raise Conflict("someone else saved first")

    monkeypatch.setattr(collection_views, "save_collection", boom)
    with override_settings(**_settings(root)):
        response = _client_as(Archivist()).post(
            f"/bestand/{FOTOS}/bearbeiten", {"name": "Lichtbilder"}
        )
    assert response.status_code == 200  # not a 500
    body = response.content.decode()
    assert "Inzwischen geändert" in body  # the conflict panel
    assert 'value="Lichtbilder"' in body  # the just-submitted name is preserved
