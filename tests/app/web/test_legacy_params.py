"""Old German query params: a GET or HEAD naming one gets a 301 to its English URL; the path stays
in its own spelling and on the site, the param order stays, an English twin wins
(``legacy_params``)."""

from urllib.parse import unquote, urlsplit

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from tests.app.web._fixtures import client_as

from bundesarchiv.app.web.legacy_params import LegacyParamsMiddleware
from bundesarchiv.domain.viewer import Archivist


@pytest.mark.parametrize("method", ["get", "head"])
def test_an_old_url_moves_permanently_to_its_english_form(method: str) -> None:
    old = "/?bestand=FOTOS&q=Fahrt&sortierung=%20-Signatur%20&seite=2&auswahl=A&auswahl=B&fokus=signatur"
    response = getattr(client_as(None), method)(old)
    assert response.status_code == 301
    assert response["Location"] == (
        "/?collection=FOTOS&q=Fahrt&sort=-ref_code&page=2&selection=A&selection=B&focus=ref_code"
    )


def test_the_english_twin_wins_over_its_old_spelling() -> None:
    response = client_as(None).get("/articles/new?bestand=AKTEN&collection=FOTOS")
    assert response["Location"] == "/articles/new?collection=FOTOS"


@pytest.mark.parametrize(
    "path",
    [
        "///evil.example/x",
        "//[evil.example",
        "/\\evil.example/x",
        "/\\/evil.example/x",
        "/x\\y",
        "/x\r\nSet-Cookie: a=1",
        "/x#y",
        "/a?b",
        "/50%41",
        "/@evil.example/x",
        "/evil.example:80/x",
    ],
)
def test_the_redirect_keeps_any_path_on_the_site_in_its_own_spelling(path: str) -> None:
    # PATH_INFO arrives decoded: a server hands these over for /%2F…, /%5C…, /x%0D%0A…, /x%23y
    request = RequestFactory().get("/?bestand=FOTOS", PATH_INFO=path)
    response = LegacyParamsMiddleware(lambda _: HttpResponse())(request)
    assert response.status_code == 301
    location = response["Location"]
    assert urlsplit(location)[:2] == ("", "")
    assert not location.startswith(("//", "/\\"))
    assert unquote(urlsplit(location).path) == path


def test_an_encoded_slash_stays_on_the_site() -> None:
    response = client_as(None).get("/%2Fevil.example/x?bestand=FOTOS")
    assert response.status_code == 301
    assert response["Location"] == "/%2Fevil.example/x?collection=FOTOS"


@pytest.mark.usefixtures("corpus")
@pytest.mark.parametrize(
    "query", ["collection=FOTOS&sort=-ref_code", "sort=nonsense", "focus=index", ""]
)
def test_an_english_url_is_served_where_it_is(query: str) -> None:
    assert client_as(Archivist()).get(f"/articles/new?{query}").status_code == 200


def test_a_post_is_never_redirected() -> None:
    # a 301 turns a POST into a GET: the write would be lost
    response = client_as(None).post("/articles/new?bestand=FOTOS", {"title": ""})
    assert response.status_code != 301
