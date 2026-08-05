"""Archivist entry points to the 4.8 Bestand routes on the workbench.

"+ Neuer Bestand" sits beside "+ Neuer Artikel" in the header (archivist-only chrome, absent for
everyone else). A per-Bestand "Bestand bearbeiten" affordance appears only when a ?bestand= filter is
active (the archivist has a specific Bestand in focus) — the simplest honest entry, no separate list
page. Neither is a visibility decision: the routes are independently archivist-gated.
"""

from pathlib import Path

import pytest
from django.core import signing
from django.test import Client, override_settings

from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Article, Audience, AudienceTier, Collection, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Public, Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

_DEV_KEY = "test-bestand-entry-key"
FOTOS = new_ulid()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    store = LocalFsObjectStore(tmp_path / "canonical")
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    collections.save(Collection("ROOT", "Bundesarchiv", None), 0)
    collections.save(Collection(FOTOS, "Fotografien", "ROOT", Audience(AudienceTier.PUBLIC)), 0)
    articles.save(
        Article(
            ulid=new_ulid(), title="Ein Foto", collection_id=FOTOS, lifecycle=Lifecycle.PUBLISHED
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


@pytest.mark.django_db
def test_archivist_workbench_shows_neuer_bestand(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get("/").content.decode()
    assert "+ Neuer Bestand" in body
    assert "/bestand/neu" in body


@pytest.mark.django_db
def test_public_workbench_hides_neuer_bestand(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Public()).get("/").content.decode()
    assert "+ Neuer Bestand" not in body
    assert "/bestand/neu" not in body


@pytest.mark.django_db
def test_edit_affordance_appears_when_a_bestand_filter_is_active(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get(f"/?bestand={FOTOS}").content.decode()
    assert f"/bestand/{FOTOS}/bearbeiten" in body  # edit the focused Bestand


@pytest.mark.django_db
def test_no_edit_affordance_without_a_bestand_filter(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Archivist()).get("/").content.decode()
    assert "/bearbeiten" not in body  # no focused Bestand → no rename affordance


@pytest.mark.django_db
def test_public_never_gets_edit_affordance(root: Path) -> None:
    with override_settings(**_settings(root)):
        body = _client_as(Public()).get(f"/?bestand={FOTOS}").content.decode()
    assert "/bearbeiten" not in body
