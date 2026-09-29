"""The 4.8 rename-Bestand form (`/bestand/<ulid>/bearbeiten`, `collection_edit`).

SLIM rename: Name field ONLY. Parent + Sichtbarkeit render as quiet READ-ONLY display rows with one
hint — moving + changing visibility are deferred. Archivist-gated both methods (404 otherwise);
a malformed/absent ulid is likewise a 404. POST saves under CAS and reindexes the subtree
(the name is live in facets on the next render). A renamed Bestand shows its new name in workbench
facets — pinned by a test.
"""

import re
from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    ROOT,
    Corpus,
    client_as,
    make_article,
    make_collection,
)

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

FOTOS = new_ulid()


@pytest.fixture
def archive(make_corpus: Callable[[], Corpus]) -> Corpus:
    """One MEMBERS Bestand holding one article. ROOT is renamed because the form prints the PARENT's
    name and a test pins it — under the shared default name that assert would pass on the page's
    wordmark alone."""
    corpus = make_corpus()
    corpus.collections.save(
        make_collection(ROOT, "Bundesarchiv", parent_id=None), 1, changed_by="tester"
    )
    corpus.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.MEMBERS))
    )
    corpus.add_article(make_article(new_ulid(), collection_id=FOTOS, title="Ein Foto"))
    return corpus


def _name_of(corpus: Corpus, ulid: str) -> str:
    return corpus.collections.load(ulid).collection.name


# --- archivist gate + 404 discipline ----------------------------------------------


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=())])
@pytest.mark.parametrize("method", ["get", "post"])
def test_non_archivist_gets_404(archive: Corpus, viewer: Viewer | None, method: str) -> None:
    response = getattr(client_as(viewer), method)(f"/bestand/{FOTOS}/bearbeiten")
    assert_denied(response)


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_malformed_or_absent_ulid_is_404(archive: Corpus, ulid: str) -> None:
    response = client_as(Archivist()).get(f"/bestand/{ulid}/bearbeiten")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_leaves_name_unchanged(archive: Corpus) -> None:
    client_as(Public()).post(f"/bestand/{FOTOS}/bearbeiten", {"name": "Gehackt"})
    assert _name_of(archive, FOTOS) == "Fotografien"  # unchanged


# --- GET renders the rename form (Name editable, parent + Sichtbarkeit read-only) --


def test_get_renders_name_field_and_readonly_rows(archive: Corpus) -> None:
    body = client_as(Archivist()).get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
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
def test_post_blank_name_re_renders_with_error_unchanged(archive: Corpus) -> None:
    response = client_as(Archivist()).post(
        f"/bestand/{FOTOS}/bearbeiten", {"name": "", "expected_version": "1"}
    )
    assert response.status_code == 200
    assert "Name ist erforderlich." in response.content.decode()
    assert _name_of(archive, FOTOS) == "Fotografien"  # unchanged


@pytest.mark.django_db
def test_rename_shows_new_name_in_workbench_facets(archive: Corpus) -> None:
    # the reindex path must surface the new name in the collection facet group (the denormalized
    # ancestors reindex + the live name resolution).
    client = client_as(Archivist())
    client.post(f"/bestand/{FOTOS}/bearbeiten", {"name": "Lichtbilder", "expected_version": "1"})
    body = client.get("/").content.decode()
    assert "Lichtbilder" in body  # the renamed Bestand's new name in the rail's Bestand dropdown
    assert "Fotografien" not in body  # the old name is gone


# --- racing rename: Conflict → the "Inzwischen geändert" panel (security LOW) --------


def _expected_version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d*)"', body)
    assert match is not None, (
        "GET must seed a hidden expected_version (parity with the article form)"
    )
    return match.group(1)


@pytest.mark.django_db
def test_stale_expected_version_loses_the_race_and_preserves_input(archive: Corpus) -> None:
    # The genuine race the brief describes: the form is GET'd at v1, a CONCURRENT rename (a second
    # archivist, or this same one in another tab) bumps the store to v2, and the ORIGINAL stale form
    # then POSTs expected_version=1. The CAS check must reject that stale version — a rename that
    # raced another rename must NOT silently win (lost update) — and re-render the "Inzwischen
    # geändert" panel with the winner's name shown and the submitted name preserved.
    client = client_as(Archivist())
    get_body = client.get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
    stale_version = _expected_version_of(get_body)
    assert stale_version == "1"

    # a concurrent rename lands first (its own fresh GET+POST at v1), bumping the store to v2
    client.post(
        f"/bestand/{FOTOS}/bearbeiten",
        {"name": "Lichtbilder", "expected_version": stale_version},
    )
    assert _name_of(archive, FOTOS) == "Lichtbilder"

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
        _name_of(archive, FOTOS) == "Lichtbilder"
    )  # the stale rename never took effect (no lost update)


@pytest.mark.django_db
def test_matching_expected_version_still_saves_and_redirects(archive: Corpus) -> None:
    # Pin: a fresh rename (matching version) still saves and redirects, now that expected_version
    # rides the form.
    client = client_as(Archivist())
    get_body = client.get(f"/bestand/{FOTOS}/bearbeiten").content.decode()
    version = _expected_version_of(get_body)
    response = client.post(
        f"/bestand/{FOTOS}/bearbeiten",
        {"name": "Lichtbilder", "expected_version": version},
    )
    assert response.status_code == 302
    assert response["Location"] == f"/?bestand={FOTOS}"
    assert _name_of(archive, FOTOS) == "Lichtbilder"
