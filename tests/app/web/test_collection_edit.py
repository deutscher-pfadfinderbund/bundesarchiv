import re
from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import (
    ROOT,
    Corpus,
    client_as,
    list_url,
    make_article,
    make_collection,
    page_forms,
)

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

FOTOS = new_ulid()


@pytest.fixture
def archive(make_corpus: Callable[[], Corpus]) -> Corpus:
    """One MEMBERS Bestand holding one article."""
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
    response = getattr(client_as(viewer), method)(f"/collections/{FOTOS}/edit")
    assert_denied(response)


@pytest.mark.parametrize("ulid", ["not-a-ulid", "01BX5ZZKBKACTAV9WEVGEMMVRZ"])
def test_malformed_or_absent_ulid_is_404(archive: Corpus, ulid: str) -> None:
    response = client_as(Archivist()).get(f"/collections/{ulid}/edit")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_leaves_name_unchanged(archive: Corpus) -> None:
    client_as(Public()).post(f"/collections/{FOTOS}/edit", {"name": "Gehackt"})
    assert _name_of(archive, FOTOS) == "Fotografien"


# --- GET renders the rename form (Name editable, parent + Sichtbarkeit read-only) --


def test_get_renders_name_field_and_readonly_rows(archive: Corpus) -> None:
    body = client_as(Archivist()).get(f"/collections/{FOTOS}/edit").content.decode()
    [fields] = [f for a, f in page_forms(body) if a == f"/collections/{FOTOS}/edit"]
    # Name is the one editable control, seeded; parent + Sichtbarkeit are shown, never posted
    assert fields.keys() == {"csrfmiddlewaretoken", "expected_version", "name"}
    assert fields["name"] == "Fotografien"
    assert "Bundesarchiv" in body  # the parent's name
    assert "Alle Mitglieder" in body  # the MEMBERS label


@pytest.mark.django_db
def test_the_page_shows_the_parent_chain_as_crumbs(archive: Corpus) -> None:
    body = client_as(Archivist()).get(f"/collections/{FOTOS}/edit").content.decode()
    crumbs = body.split('class="crumbs"')[1].split("</nav>")[0]
    assert f"?collection={ROOT}" in crumbs
    assert f"?collection={FOTOS}" in crumbs


# --- POST renames -----------------------------------------------------------------


@pytest.mark.django_db
def test_post_blank_name_re_renders_with_error_unchanged(archive: Corpus) -> None:
    response = client_as(Archivist()).post(
        f"/collections/{FOTOS}/edit", {"name": "", "expected_version": "1"}
    )
    assert response.status_code == 200
    assert "Name ist erforderlich." in response.content.decode()
    assert _name_of(archive, FOTOS) == "Fotografien"


@pytest.mark.django_db
def test_a_pasted_line_break_in_the_name_becomes_a_space(archive: Corpus) -> None:
    """The name is the README's H1 line (ADR 0019)."""
    client_as(Archivist()).post(
        f"/collections/{FOTOS}/edit",
        {"name": "Licht\N{LINE SEPARATOR}bilder\r\n", "expected_version": "1"},
    )
    assert _name_of(archive, FOTOS) == "Licht bilder"


@pytest.mark.django_db
def test_rename_shows_new_name_in_workbench_facets(archive: Corpus) -> None:
    client = client_as(Archivist())
    client.post(f"/collections/{FOTOS}/edit", {"name": "Lichtbilder", "expected_version": "1"})
    body = client.get(list_url()).content.decode()
    assert "Lichtbilder" in body
    assert "Fotografien" not in body


# --- racing rename: Conflict → the "Inzwischen geändert" panel ---


def _expected_version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d*)"', body)
    assert match is not None, (
        "GET must seed a hidden expected_version (parity with the article form)"
    )
    return match.group(1)


@pytest.mark.django_db
def test_stale_expected_version_loses_the_race_and_preserves_input(archive: Corpus) -> None:
    client = client_as(Archivist())
    get_body = client.get(f"/collections/{FOTOS}/edit").content.decode()
    stale_version = _expected_version_of(get_body)
    assert stale_version == "1"

    # the other tab saves first
    client.post(
        f"/collections/{FOTOS}/edit",
        {"name": "Lichtbilder", "expected_version": stale_version},
    )
    assert _name_of(archive, FOTOS) == "Lichtbilder"

    response = client.post(
        f"/collections/{FOTOS}/edit",
        {"name": "Gestohlen", "expected_version": stale_version},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Inzwischen geändert" in body
    assert "Lichtbilder" in body
    assert 'value="Gestohlen"' in body
    assert _expected_version_of(body) == "2"
    assert _name_of(archive, FOTOS) == "Lichtbilder"


@pytest.mark.django_db
def test_matching_expected_version_still_saves_and_redirects(archive: Corpus) -> None:
    client = client_as(Archivist())
    get_body = client.get(f"/collections/{FOTOS}/edit").content.decode()
    version = _expected_version_of(get_body)
    response = client.post(
        f"/collections/{FOTOS}/edit",
        {"name": "Lichtbilder", "expected_version": version},
    )
    assert response.status_code == 302
    assert response["Location"] == f"/articles?collection={FOTOS}"
    assert _name_of(archive, FOTOS) == "Lichtbilder"


@pytest.mark.django_db
def test_the_panel_answers_a_race_in_place_then_saves(archive: Corpus) -> None:
    client = client_as(Archivist())
    client.post(f"/collections/{FOTOS}/edit", {"name": "Lichtbilder", "expected_version": "1"})
    refused = client.post(
        f"/collections/{FOTOS}/edit",
        {"name": "Meins", "expected_version": "1"},
        headers={"HX-Request": "true"},
    )
    [(action, fields)] = page_forms(refused.content.decode())
    assert action == f"/collections/{FOTOS}/edit"
    assert fields["name"] == "Meins"
    assert fields["expected_version"] == "2"
    assert _name_of(archive, FOTOS) == "Lichtbilder"
    saved = client.post(action, fields, headers={"HX-Request": "true"})
    assert saved["HX-Redirect"] == f"/articles?collection={FOTOS}"
    assert _name_of(archive, FOTOS) == "Meins"
