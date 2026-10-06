"""Archivist entry points to the 4.8 Bestand routes on the workbench.

"Neuer Bestand" lives beside "Neuer Artikel" in the header's "+ Neu …" disclosure panel (Mock B,
owner 2026-08-07 — archivist-only chrome, absent for everyone else). A per-Bestand "Bestand
bearbeiten" button sits in the list's tool row (or, while the Bestand is empty, in its empty state)
only when a ?collection= filter is active (the archivist has a specific Bestand in focus), not in the
menu. Neither is a visibility decision: the routes are
independently archivist-gated.
"""

from collections.abc import Callable

import pytest
from tests.app.web._fixtures import Corpus, client_as, list_url, make_collection, page_forms

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Public

FOTOS = new_ulid()


@pytest.fixture
def focussed(make_corpus: Callable[[], Corpus]) -> Corpus:
    """An archive whose one Bestand carries a real ULID — the edit affordance links to
    /collections/<ulid>/edit, a route that rejects anything else as malformed."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    return corpus


@pytest.mark.django_db
def test_archivist_workbench_shows_neuer_bestand(corpus: Corpus) -> None:
    body = client_as(Archivist()).get(list_url()).content.decode()
    assert "Neuer Bestand" in body
    assert "/collections/new" in body


@pytest.mark.django_db
def test_public_workbench_hides_neuer_bestand(corpus: Corpus) -> None:
    body = client_as(Public()).get(list_url()).content.decode()
    assert "Neuer Bestand" not in body
    assert "/collections/new" not in body


@pytest.mark.django_db
def test_edit_affordance_appears_when_a_bestand_filter_is_active(focussed: Corpus) -> None:
    body = client_as(Archivist()).get(list_url(collection=FOTOS)).content.decode()
    assert f"/collections/{FOTOS}/edit" in body  # edit the focused Bestand


@pytest.mark.django_db
def test_the_rename_opens_from_the_list_and_not_from_the_menu(focussed: Corpus) -> None:
    body = client_as(Archivist()).get(list_url(collection=FOTOS)).content.decode()
    menu = body.split('id="neu-menu"')[1].split("</ul>")[0]
    assert 'popovertarget="collection-edit"' in body
    assert "collection-edit" not in menu
    assert 'id="collection-edit"' in body  # the panel the list's button opens


@pytest.mark.django_db
def test_an_empty_bestand_offers_the_new_article_panel_with_itself_preselected(
    focussed: Corpus,
) -> None:
    body = client_as(Archivist()).get(list_url(collection=FOTOS)).content.decode()
    empty = body.split('class="empty-state"')[1]
    assert 'popovertarget="neu-artikel"' in empty
    assert 'popovertarget="collection-edit"' in empty  # no rows, no tool row: renamed from here
    panel = body.split('id="neu-artikel"')[1].split("</form>")[0]
    assert f'<option value="{FOTOS}" selected>' in panel


@pytest.mark.django_db
def test_no_edit_affordance_without_a_bestand_filter(focussed: Corpus) -> None:
    body = client_as(Archivist()).get(list_url()).content.decode()
    assert "/edit" not in body  # no focused Bestand → no rename affordance


@pytest.mark.django_db
def test_public_never_gets_edit_affordance(focussed: Corpus) -> None:
    body = client_as(Public()).get(list_url(collection=FOTOS)).content.decode()
    assert "/edit" not in body


@pytest.mark.django_db
def test_the_header_creates_a_bestand_from_an_archivist_page(focussed: Corpus) -> None:
    client = client_as(Archivist())
    body = client.get(list_url(collection=FOTOS)).content.decode()
    [fields] = [f for action, f in page_forms(body) if action == "/collections/new"]
    client.post("/collections/new", {**fields, "name": "Rover"})
    assert "Rover" in {c.name for c in focussed.collections.load_all()}


@pytest.mark.django_db
def test_the_scoped_list_renames_against_the_version_it_showed(focussed: Corpus) -> None:
    """The list's "Bestand bearbeiten" panel renames against the version it was rendered for: it
    saves, and the same panel, now stale, overwrites nothing."""
    client = client_as(Archivist())
    body = client.get(list_url(collection=FOTOS)).content.decode()
    [(action, fields)] = [(a, f) for a, f in page_forms(body) if a.endswith("/edit")]
    client.post(action, {**fields, "name": "Lichtbilder"})
    assert focussed.collections.load(FOTOS).collection.name == "Lichtbilder"
    client.post(action, {**fields, "name": "Meins"})
    assert focussed.collections.load(FOTOS).collection.name == "Lichtbilder"
