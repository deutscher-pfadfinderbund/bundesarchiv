"""Archivist entry points to the 4.8 Bestand routes on the workbench.

"Neuer Bestand" lives beside "Neuer Artikel" in the header's "+ Neu …" disclosure panel (Mock B,
owner 2026-08-07 — archivist-only chrome, absent for everyone else). A per-Bestand "Bestand
bearbeiten" affordance joins the panel only when a ?bestand= filter is active (the archivist has a
specific Bestand in focus) — the simplest honest entry, no separate list page. Neither is a
visibility decision: the routes are independently archivist-gated.
"""

from collections.abc import Callable

import pytest
from tests.app.web._fixtures import Corpus, client_as, make_collection, page_forms

from bundesarchiv.domain.identity import new_ulid
from bundesarchiv.domain.models import Audience, AudienceTier
from bundesarchiv.domain.viewer import Archivist, Public

FOTOS = new_ulid()


@pytest.fixture
def focussed(make_corpus: Callable[[], Corpus]) -> Corpus:
    """An archive whose one Bestand carries a real ULID — the edit affordance links to
    /bestand/<ulid>/bearbeiten, a route that rejects anything else as malformed."""
    corpus = make_corpus()
    corpus.add_collection(
        make_collection(FOTOS, "Fotografien", audience=Audience(AudienceTier.PUBLIC))
    )
    return corpus


@pytest.mark.django_db
def test_archivist_workbench_shows_neuer_bestand(corpus: Corpus) -> None:
    body = client_as(Archivist()).get("/").content.decode()
    assert "Neuer Bestand" in body
    assert "/bestand/neu" in body


@pytest.mark.django_db
def test_public_workbench_hides_neuer_bestand(corpus: Corpus) -> None:
    body = client_as(Public()).get("/").content.decode()
    assert "Neuer Bestand" not in body
    assert "/bestand/neu" not in body


@pytest.mark.django_db
def test_edit_affordance_appears_when_a_bestand_filter_is_active(focussed: Corpus) -> None:
    body = client_as(Archivist()).get(f"/?bestand={FOTOS}").content.decode()
    assert f"/bestand/{FOTOS}/bearbeiten" in body  # edit the focused Bestand


@pytest.mark.django_db
def test_no_edit_affordance_without_a_bestand_filter(focussed: Corpus) -> None:
    body = client_as(Archivist()).get("/").content.decode()
    assert "/bearbeiten" not in body  # no focused Bestand → no rename affordance


@pytest.mark.django_db
def test_public_never_gets_edit_affordance(focussed: Corpus) -> None:
    body = client_as(Public()).get(f"/?bestand={FOTOS}").content.decode()
    assert "/bearbeiten" not in body


@pytest.mark.django_db
def test_the_header_creates_a_bestand_from_an_archivist_page(focussed: Corpus) -> None:
    client = client_as(Archivist())
    body = client.get(f"/?bestand={FOTOS}").content.decode()
    [fields] = [f for action, f in page_forms(body) if action == "/bestand/neu"]
    client.post("/bestand/neu", {**fields, "name": "Rover"})
    assert "Rover" in {c.name for c in focussed.collections.load_all()}


@pytest.mark.django_db
def test_the_scoped_list_renames_against_the_version_it_showed(focussed: Corpus) -> None:
    """The list's "Bestand bearbeiten" panel renames against the version it was rendered for: it
    saves, and the same panel, now stale, overwrites nothing."""
    client = client_as(Archivist())
    body = client.get(f"/?bestand={FOTOS}").content.decode()
    [(action, fields)] = [(a, f) for a, f in page_forms(body) if a.endswith("/bearbeiten")]
    client.post(action, {**fields, "name": "Lichtbilder"})
    assert focussed.collections.load(FOTOS).collection.name == "Lichtbilder"
    client.post(action, {**fields, "name": "Meins"})
    assert focussed.collections.load(FOTOS).collection.name == "Lichtbilder"
