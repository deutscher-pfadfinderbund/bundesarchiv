"""Archivist entry points to the 4.8 Bestand routes on the workbench.

"Neuer Bestand" lives beside "Neuer Artikel" in the header's "+ Neu …" disclosure panel (Mock B,
owner 2026-08-07 — archivist-only chrome, absent for everyone else). A per-Bestand "Bestand
bearbeiten" affordance joins the panel only when a ?bestand= filter is active (the archivist has a
specific Bestand in focus) — the simplest honest entry, no separate list page. Neither is a
visibility decision: the routes are independently archivist-gated.
"""

from collections.abc import Callable

import pytest
from tests.app.web._fixtures import Corpus, client_as, make_collection

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
