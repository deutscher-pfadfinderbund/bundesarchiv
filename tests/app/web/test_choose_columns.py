"""``POST /columns`` — the "Spalten …" choice: kept in a cookie, then back to the same list (PRG).

The route writes no archive and reads no index; what it may never do is redirect off the site or
store anything but registry keys."""

from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.http import HttpResponse
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import client_as

from bundesarchiv.app.web import ledger
from bundesarchiv.domain.viewer import Member

#: the web suite's settings (the dev-viewer key, the prod urlconf) come with the standard corpus
pytestmark = pytest.mark.usefixtures("corpus")


def _post(data: dict[str, object], *, enforce_csrf: bool = False) -> HttpResponse:
    client = client_as(Member(groups=()), enforce_csrf=enforce_csrf)
    return cast(HttpResponse, client.post("/columns", data))


def test_the_choice_lands_in_the_cookie_and_the_list_returns_with_its_query() -> None:
    query = "q=Fahrt+%26+Lager&collection=B1&sort=-date&selection=A1&selection=A2&article=A1"
    response = _post({"spalte": ["collection", "date"], "zurueck": query})
    assert response.status_code == 302
    target = urlsplit(response["Location"])
    assert (target.scheme, target.netloc, target.path) == ("", "", "/articles")
    assert parse_qs(target.query) == parse_qs(query)
    cookie = response.cookies[ledger.COOKIE]
    assert cookie.value == ledger.cookie_value(["collection", "date"])
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"
    assert bool(cookie["secure"]) is settings.CSRF_COOKIE_SECURE
    assert int(cookie["max-age"]) == ledger.COOKIE_MAX_AGE


@pytest.mark.parametrize(
    "zurueck",
    [
        "//evil.example/liste",
        "https://evil.example/",
        "/\\evil.example",
        "@evil.example",
        "q=x\r\nLocation: https://evil.example",
        "",
    ],
)
def test_the_way_back_never_leaves_the_site(zurueck: str) -> None:
    target = urlsplit(_post({"spalte": ["date"], "zurueck": zurueck})["Location"])
    assert (target.scheme, target.netloc, target.path) == ("", "", "/articles")


def test_the_cookie_never_holds_a_posted_value_that_names_no_column() -> None:
    response = _post({"spalte": ["<script>", "type.collection", "date"], "zurueck": ""})
    assert response.cookies[ledger.COOKIE].value == ledger.cookie_value(["date"])


def test_a_get_is_the_plain_404_and_sets_nothing() -> None:
    response = client_as(Member(groups=())).get("/columns?spalte=bestand")
    assert_denied(response)
    assert ledger.COOKIE not in response.cookies


def test_a_cross_site_post_is_refused_and_sets_nothing() -> None:
    response = _post({"spalte": ["collection"], "zurueck": ""}, enforce_csrf=True)
    assert response.status_code == 403
    assert ledger.COOKIE not in response.cookies
