"""Old German query params: a GET or HEAD naming one gets a 301 to its English URL; the path stays,
the param order stays, an English twin wins (``legacy_params``)."""

import pytest
from tests.app.web._fixtures import client_as

from bundesarchiv.domain.viewer import Archivist


@pytest.mark.parametrize("method", ["get", "head"])
def test_an_old_url_moves_permanently_to_its_english_form(method: str) -> None:
    old = "/?bestand=FOTOS&q=Fahrt&sortierung=%20-Signatur%20&seite=2&auswahl=A&auswahl=B&fokus=signatur"
    response = getattr(client_as(Archivist()), method)(old)
    assert response.status_code == 301
    assert response["Location"] == (
        "/?collection=FOTOS&q=Fahrt&sort=-ref_code&page=2&selection=A&selection=B&focus=ref_code"
    )


def test_the_english_twin_wins_over_its_old_spelling() -> None:
    response = client_as(Archivist()).get("/articles/new?bestand=AKTEN&collection=FOTOS")
    assert response["Location"] == "/articles/new?collection=FOTOS"


@pytest.mark.parametrize(
    "query", ["collection=FOTOS&sort=-ref_code", "sort=nonsense", "focus=index", ""]
)
def test_an_english_url_is_served_where_it_is(query: str) -> None:
    assert client_as(Archivist()).get(f"/articles/new?{query}").status_code == 200


def test_a_post_is_never_redirected() -> None:
    # a 301 turns a POST into a GET: the write would be lost
    response = client_as(Archivist()).post("/collections/new?bestand=FOTOS", {"audience": ""})
    assert response.status_code != 301
