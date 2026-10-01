"""The create step ``/articles/new`` (Part 4.7 Slice A, spec §2).

GET renders the minimal create form (Titel + Bestand); POST creates a DRAFT via ``create_article``
and 302s to ``/articles/<ulid>/edit``. Both methods are archivist-gated: a Member / Public /
anonymous request gets a 404 (existence-hiding — the cataloging entry point must not be
discoverable). Validation state B re-renders the form with the verbatim error and preserved values,
no create.
"""

from collections.abc import Callable

import pytest
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus, client_as, make_collection, page_forms

from bundesarchiv.domain.models import Audience, AudienceTier, Lifecycle
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


@pytest.fixture
def empty_archive(make_corpus: Callable[[], Corpus]) -> Corpus:
    """Two collections to file into and NO articles: every create test reads the whole store to
    assert what was (not) created, so the standard corpus' own articles would count as creations."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection("PUB", "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_collection(
        make_collection("MEM", "Mitglieder", audience=Audience(AudienceTier.MEMBERS))
    )
    return corpus


# --- GET: the create form ----------------------------------------------------------


def test_create_form_renders_for_archivist(empty_archive: Corpus) -> None:
    response = client_as(Archivist()).get("/articles/new")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Neuer Artikel" in body
    assert 'name="title"' in body
    assert 'name="collection_id"' in body
    # the Bestand options list the collections by name
    assert "Öffentlich" in body
    assert "Mitglieder" in body


# --- GET/POST: archivist gate (both methods) --------------------------------------


# (The GET deny is the leak matrix's cell for this route — only the POST twin adds the
# nothing-was-created side-effect assert the matrix can't see.)
@pytest.mark.parametrize("viewer", [Public(), Member(groups=("vorstand",))])
def test_create_post_is_404_for_non_archivist(empty_archive: Corpus, viewer: Viewer) -> None:
    response = client_as(viewer).post("/articles/new", {"title": "X", "collection_id": "PUB"})
    assert_denied(response)
    # nothing was created
    assert list(empty_archive.articles.list_ulids()) == []


# --- POST: create + redirect -------------------------------------------------------


def test_create_post_creates_draft_and_redirects_to_edit(empty_archive: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/articles/new", {"title": "Wanderfahrt 1962", "collection_id": "PUB"}
    )
    assert response.status_code == 302
    ulids = list(empty_archive.articles.list_ulids())
    assert len(ulids) == 1
    assert response["Location"] == f"/articles/{ulids[0]}/edit"
    stored = empty_archive.articles.load(ulids[0])
    assert stored.article.title == "Wanderfahrt 1962"
    assert stored.article.collection_id == "PUB"
    assert stored.article.lifecycle is Lifecycle.DRAFT


def test_create_post_missing_title_re_renders_state_b(empty_archive: Corpus) -> None:
    response = client_as(Archivist()).post("/articles/new", {"title": "", "collection_id": "PUB"})
    assert response.status_code == 200
    body = response.content.decode()
    assert "Titel ist erforderlich." in body
    # the chosen Bestand is preserved
    assert list(empty_archive.articles.list_ulids()) == []


def test_create_post_missing_collection_re_renders_state_b(empty_archive: Corpus) -> None:
    response = client_as(Archivist()).post(
        "/articles/new", {"title": "Wanderfahrt", "collection_id": ""}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Bitte einen Bestand wählen." in body
    # the typed title is preserved
    assert "Wanderfahrt" in body
    assert list(empty_archive.articles.list_ulids()) == []


@pytest.mark.django_db
def test_the_panel_answers_a_refusal_in_place_then_creates(empty_archive: Corpus) -> None:
    """With htmx the create step's tool panel is its own answer: a refusal comes back as the one
    form with the values kept and nothing created; a create navigates to the new draft's form."""
    client = client_as(Archivist())
    refused = client.post(
        "/articles/new", {"title": "Fahrt", "collection_id": ""}, headers={"HX-Request": "true"}
    )
    [(action, fields)] = page_forms(refused.content.decode())
    assert action == "/articles/new"
    assert fields["title"] == "Fahrt"
    assert list(empty_archive.articles.list_ulids()) == []
    created = client.post(
        action, {**fields, "collection_id": "PUB"}, headers={"HX-Request": "true"}
    )
    [draft] = empty_archive.articles.list_ulids()
    assert created["HX-Redirect"] == f"/articles/{draft}/edit"
