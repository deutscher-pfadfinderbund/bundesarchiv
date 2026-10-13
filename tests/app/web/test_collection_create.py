from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_collection, page_forms

from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@pytest.fixture
def fotos(make_corpus: Callable[[], Corpus]) -> Corpus:
    corpus = make_corpus()
    corpus.add_collection(
        make_collection("FOTOS", "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    return corpus


# --- archivist gate + 404 discipline ----------------------------------------------


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=())])
@pytest.mark.parametrize("method", ["get", "post"])
def test_non_archivist_gets_404(corpus: Corpus, viewer: Viewer | None, method: str) -> None:
    response = getattr(client_as(viewer), method)("/collections/new")
    assert_denied(response)


@pytest.mark.django_db
def test_non_archivist_post_creates_nothing(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    client_as(Public()).post("/collections/new", {"name": "Heimlich", "parent_id": ""})
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.parametrize(
    "post",
    [{}, {"audience": "bogus", "groups": "x"}, {"groups": "vorstand"}],
    ids=["absent", "unknown", "groups-only"],
)
def test_a_create_naming_no_rung_is_denied_and_creates_nothing(
    corpus: Corpus, post: dict[str, str]
) -> None:
    # a create has no stored audience to keep, and no rung is narrow enough to assume
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post("/collections/new", {"name": "Karten", **post})
    assert_denied(response)
    assert {c.ulid for c in corpus.collections.load_all()} == before


# --- GET renders the form ---------------------------------------------------------


def test_get_renders_form_with_parent_and_visibility(fotos: Corpus) -> None:
    body = client_as(Archivist()).get("/collections/new").content.decode()
    assert "Neuer Bestand" in body
    assert 'name="name"' in body
    assert 'name="parent_id"' in body
    assert "Fotografien" in body
    assert "Vom Bestand erben" in body
    assert "Öffentlich" in body


# --- POST creates -----------------------------------------------------------------


@pytest.mark.django_db
def test_post_creates_top_level_and_lands_on_catalog_form(corpus: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/collections/new", {"name": "Karten", "parent_id": "", "audience": ""}
    )
    assert response.status_code == 302
    created = [c for c in corpus.collections.load_all() if c.name == "Karten"]
    assert len(created) == 1
    assert created[0].parent_id is None
    assert created[0].audience is None
    location = response["Location"]
    assert location.startswith("/articles/new?")
    assert f"collection={created[0].ulid}" in location
    assert "created=1" in location


@pytest.mark.django_db
def test_catalog_form_preselects_collection_and_shows_hinweis(fotos: Corpus) -> None:
    body = client_as(Archivist()).get("/articles/new?collection=FOTOS&created=1").content.decode()
    assert 'value="FOTOS" selected' in body
    assert "Bestand „Fotografien“ angelegt." in body  # the name is looked up, not read from the URL


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    ["created=<b>Geheim</b>", "created=Fotografien", "created=1", "collection=NOSUCH&created=1"],
)
def test_created_shows_no_text_from_the_url(fotos: Corpus, query: str) -> None:
    body = client_as(Archivist()).get(f"/articles/new?{query}").content.decode()
    assert "angelegt." not in body
    assert "Geheim" not in body


@pytest.mark.django_db
def test_catalog_form_ignores_a_bogus_preselect(fotos: Corpus) -> None:
    # no existence oracle
    body = client_as(Archivist()).get("/articles/new?collection=NOSUCH").content.decode()
    assert 'value="FOTOS" selected' not in body
    assert 'value="" selected' in body


@pytest.mark.django_db
def test_post_creates_under_parent_with_members_audience(fotos: Corpus) -> None:
    client_as(Archivist()).post(
        "/collections/new",
        {"name": "Interna", "parent_id": "FOTOS", "audience": "members"},
    )
    created = [c for c in fotos.collections.load_all() if c.name == "Interna"]
    assert len(created) == 1
    assert created[0].parent_id == "FOTOS"
    assert created[0].audience == Audience(AudienceTier.MEMBERS)


@pytest.mark.django_db
def test_post_creates_groups_audience_with_groups(corpus: Corpus) -> None:
    client_as(Archivist()).post(
        "/collections/new",
        {
            "name": "Vorstand",
            "parent_id": "",
            "audience": "groups",
            "groups": "vorstand\r\narchiv",
        },
    )
    created = [c for c in corpus.collections.load_all() if c.name == "Vorstand"]
    assert created[0].audience == Audience(AudienceTier.GROUPS, groups=("vorstand", "archiv"))


# --- validation -------------------------------------------------------------------


@pytest.mark.django_db
def test_post_blank_name_re_renders_with_error_and_creates_nothing(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post(
        "/collections/new", {"name": "", "parent_id": "", "audience": ""}
    )
    assert response.status_code == 200
    assert "Name ist erforderlich." in response.content.decode()
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.django_db
def test_post_groups_without_groups_re_renders_with_error(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post(
        "/collections/new",
        {"name": "Leer", "parent_id": "", "audience": "groups", "groups": ""},
    )
    assert response.status_code == 200
    assert "Bitte mindestens eine Gruppe angeben." in response.content.decode()
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.django_db
def test_post_unknown_parent_re_renders_and_creates_nothing(corpus: Corpus) -> None:
    before = {c.ulid for c in corpus.collections.load_all()}
    response = client_as(Archivist()).post(
        "/collections/new", {"name": "Waise", "parent_id": "NOSUCH", "audience": ""}
    )
    assert response.status_code == 200
    assert {c.ulid for c in corpus.collections.load_all()} == before


@pytest.mark.django_db
def test_the_panel_answers_a_refusal_in_place_then_creates(corpus: Corpus) -> None:
    client = client_as(Archivist())
    before = len(corpus.collections.load_all())
    refused = client.post(
        "/collections/new",
        {"name": "", "parent_id": "", "audience": "groups", "groups": "Rover"},
        headers={"HX-Request": "true"},
    )
    [(action, fields)] = page_forms(refused.content.decode())
    assert action == "/collections/new"
    assert (fields["audience"], fields["groups"]) == ("groups", "Rover")
    assert len(corpus.collections.load_all()) == before
    created = client.post(action, {**fields, "name": "Rover"}, headers={"HX-Request": "true"})
    assert created["HX-Redirect"].startswith("/articles/new?collection=")
    assert len(corpus.collections.load_all()) == before + 1
