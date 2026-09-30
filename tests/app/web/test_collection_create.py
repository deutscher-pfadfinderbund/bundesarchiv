"""The 4.8 create-Bestand form (`/bestand/neu`, `collection_create`).

Archivist-gated both methods (plain 404 otherwise, nothing created). GET renders the
minimal form (Name + Eltern-Bestand + Sichtbarkeit); POST validates (Name required, parent must be a
real collection or the empty top-level option, GROUPS-iff), creates the Collection, and 302s to the
workbench. Setting audience at creation is safe (a fresh collection is empty). Reuses the 4.7 form
grammar wholesale.

Pure request-handling against a local FS store — no Postgres for the gate/render tests; the create
path indexes, so those are django_db.
"""

from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_collection, page_forms

from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@pytest.fixture
def fotos(make_corpus: Callable[[], Corpus]) -> Corpus:
    """An archive holding one named Bestand — the parent option the create form offers, and the
    collection the catalog form's ``?bestand=`` preselect resolves against."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection("FOTOS", "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    return corpus


# --- archivist gate + 404 discipline ----------------------------------------------


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=())])
@pytest.mark.parametrize("method", ["get", "post"])
def test_non_archivist_gets_404(corpus: Corpus, viewer: Viewer | None, method: str) -> None:
    response = getattr(client_as(viewer), method)("/bestand/neu")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_creates_nothing(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    client_as(Public()).post("/bestand/neu", {"name": "Heimlich", "parent_id": ""})
    assert {c.ulid for c in corpus.collections.load_all()} == before  # nothing created


# --- GET renders the form ---------------------------------------------------------


def test_get_renders_form_with_parent_and_sichtbarkeit(fotos: Corpus) -> None:
    body = client_as(Archivist()).get("/bestand/neu").content.decode()
    assert "Neuer Bestand" in body
    assert 'name="name"' in body  # Name field
    assert 'name="parent_id"' in body  # Eltern-Bestand select
    assert "Fotografien" in body  # an existing collection is an option
    assert "Vom Bestand erben" in body  # the Sichtbarkeit inherit default
    assert "Öffentlich" in body


# --- POST creates -----------------------------------------------------------------


@pytest.mark.django_db
def test_post_creates_top_level_and_lands_on_catalog_form(corpus: Corpus) -> None:
    # BLOCKER 2: create → land on /artikel/neu with the new Bestand pre-selected + a success hinweis
    # (create→catalog is one flow).
    response = client_as(Archivist()).post(
        "/bestand/neu", {"name": "Karten", "parent_id": "", "sichtbarkeit": ""}
    )
    assert response.status_code == 302
    created = [c for c in corpus.collections.load_all() if c.name == "Karten"]
    assert len(created) == 1
    assert created[0].parent_id is None
    assert created[0].audience is None  # inherit
    # lands on the create-article form, pre-selecting the new Bestand + carrying its name
    location = response["Location"]
    assert location.startswith("/artikel/neu?")
    assert f"bestand={created[0].ulid}" in location
    assert "angelegt=Karten" in location


@pytest.mark.django_db
def test_catalog_form_preselects_bestand_and_shows_hinweis(fotos: Corpus) -> None:
    body = (
        client_as(Archivist())
        .get("/artikel/neu?bestand=FOTOS&angelegt=Fotografien")
        .content.decode()
    )
    assert 'value="FOTOS" selected' in body  # the Bestand pre-selected in the collection select
    assert "Bestand „Fotografien“ angelegt." in body  # the success status line


@pytest.mark.django_db
def test_catalog_form_ignores_a_bogus_preselect(fotos: Corpus) -> None:
    # a ?bestand outside the real set is ignored (no oracle) — no REAL collection is pre-selected
    # (the empty placeholder stays selected, as when no ?bestand is given at all).
    body = client_as(Archivist()).get("/artikel/neu?bestand=NOSUCH").content.decode()
    assert 'value="FOTOS" selected' not in body
    assert 'value="" selected' in body  # the placeholder is the selected option


@pytest.mark.django_db
def test_post_creates_under_parent_with_members_audience(fotos: Corpus) -> None:
    client_as(Archivist()).post(
        "/bestand/neu",
        {"name": "Interna", "parent_id": "FOTOS", "sichtbarkeit": "members"},
    )
    created = [c for c in fotos.collections.load_all() if c.name == "Interna"]
    assert len(created) == 1
    assert created[0].parent_id == "FOTOS"
    assert created[0].audience == Audience(AudienceTier.MEMBERS)


@pytest.mark.django_db
def test_post_creates_groups_audience_with_gruppen(corpus: Corpus) -> None:
    client_as(Archivist()).post(
        "/bestand/neu",
        {
            "name": "Vorstand",
            "parent_id": "",
            "sichtbarkeit": "groups",
            "gruppen": "vorstand, archiv",
        },
    )
    created = [c for c in corpus.collections.load_all() if c.name == "Vorstand"]
    assert created[0].audience == Audience(AudienceTier.GROUPS, groups=("vorstand", "archiv"))


# --- validation -------------------------------------------------------------------


@pytest.mark.django_db
def test_post_blank_name_re_renders_with_error_and_creates_nothing(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post("/bestand/neu", {"name": "", "parent_id": ""})
    assert response.status_code == 200  # re-render, not redirect
    assert "Name ist erforderlich." in response.content.decode()
    assert {c.ulid for c in corpus.collections.load_all()} == before  # nothing created


@pytest.mark.django_db
def test_post_groups_without_gruppen_re_renders_with_error(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post(
        "/bestand/neu",
        {"name": "Leer", "parent_id": "", "sichtbarkeit": "groups", "gruppen": ""},
    )
    assert response.status_code == 200
    assert "Bitte mindestens eine Gruppe angeben." in response.content.decode()
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.django_db
def test_post_unknown_parent_re_renders_and_creates_nothing(corpus: Corpus) -> None:
    # a parent_id outside the real collection set is refused (validated against the actual set — no
    # oracle) — nothing created.
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post("/bestand/neu", {"name": "Waise", "parent_id": "NOSUCH"})
    assert response.status_code == 200
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.django_db
def test_the_panel_answers_a_refusal_in_place_then_creates(corpus: Corpus) -> None:
    """With htmx the create's tool panel is its own answer: a refusal comes back as the one form
    with the values kept and nothing created; a create navigates to the catalog step."""
    client = client_as(Archivist())
    before = len(corpus.collections.load_all())
    refused = client.post(
        "/bestand/neu",
        {"name": "", "parent_id": "", "sichtbarkeit": "groups", "gruppen": "Rover"},
        headers={"HX-Request": "true"},
    )
    [(action, fields)] = page_forms(refused.content.decode())
    assert action == "/bestand/neu"
    assert (fields["sichtbarkeit"], fields["gruppen"]) == ("groups", "Rover")
    assert len(corpus.collections.load_all()) == before
    created = client.post(action, {**fields, "name": "Rover"}, headers={"HX-Request": "true"})
    assert created["HX-Redirect"].startswith("/artikel/neu?bestand=")
    assert len(corpus.collections.load_all()) == before + 1
