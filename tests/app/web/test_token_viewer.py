"""OIDC viewers from the token cookies (ADR 0018): check, refresh, and what the response carries.

The tokens are the dev realm's (``BUNDESARCHIV_REALM``); ``viewer_of`` and ``TokenCookieMiddleware``
run for real.
"""

import logging
from collections.abc import Callable, Iterator, Mapping

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, override_settings
from tests.app.web._fixtures import Asked, RecordingRealm, dev_realm_settings

from bundesarchiv.app.web.dev_realm import DevRealm
from bundesarchiv.app.web.viewers import (
    TokenCookieMiddleware,
    delete_token_cookies,
    login_cookies,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: The test settings serve https, so these are the ``__Host-`` names.
_COOKIES = login_cookies()

_ARCHIVIST: Mapping[str, object] = {
    "preferred_username": "anna",
    "realm_access": {"roles": ["Bundesarchiv"]},
}
_MEMBER: Mapping[str, object] = {"groups": ["/DPB/Bundesführung"]}


@pytest.fixture
def asked() -> Iterator[Asked]:
    calls: Asked = []
    with override_settings(**dev_realm_settings(RecordingRealm(calls))):
        yield calls


def _refreshed(asked: Asked) -> list[str | None]:
    return [args["refresh_token"] for name, args in asked if name == "refresh"]


def _tokens(claims: Mapping[str, object] = _ARCHIVIST, *, lifetime: int = 60) -> tuple[str, str]:
    tokens = DevRealm(lifetime=lifetime).mint_tokens(claims)
    assert tokens is not None
    return tokens.access, tokens.refresh


def _served(
    cookies: Mapping[str, str], view: Callable[[HttpRequest], HttpResponse] | None = None
) -> tuple[Viewer, HttpResponse]:
    """One request through the real middleware to a view that resolves the viewer (twice, as the
    gate and the view both do)."""
    request = RequestFactory().get("/")
    request.COOKIES.update(cookies)
    seen: dict[str, Viewer] = {}

    def resolve(req: HttpRequest) -> HttpResponse:
        viewer_of(req)
        seen["viewer"] = viewer_of(req)
        return view(req) if view else HttpResponse()

    response = TokenCookieMiddleware(resolve)(request)
    return seen["viewer"], response


def test_a_valid_access_token_is_the_viewer(asked: Asked) -> None:
    access, refresh = _tokens()
    viewer, response = _served({_COOKIES.access: access, _COOKIES.refresh: refresh})
    assert viewer == Archivist(username="anna")
    assert _refreshed(asked) == []
    assert not response.cookies


def test_groups_come_from_the_token(asked: Asked) -> None:
    access, _ = _tokens(_MEMBER)
    viewer, _ = _served({_COOKIES.access: access})
    assert viewer == Member(groups=("/DPB/Bundesführung",))


@pytest.mark.parametrize(
    "expired_access", [True, False], ids=["expired-access", "no-access-cookie"]
)
def test_a_refresh_renews_the_viewer_and_both_cookies(asked: Asked, expired_access: bool) -> None:
    expired, refresh = _tokens(lifetime=-1)
    cookies = {_COOKIES.refresh: refresh} | ({_COOKIES.access: expired} if expired_access else {})
    viewer, response = _served(cookies)
    assert viewer == Archivist(username="anna")
    assert DevRealm().verify_access(response.cookies[_COOKIES.access].value) is not None
    assert DevRealm().refresh(response.cookies[_COOKIES.refresh].value) is not None
    for name in (_COOKIES.access, _COOKIES.refresh):
        morsel = response.cookies[name]
        assert morsel["httponly"] and morsel["secure"] and morsel["samesite"] == "Lax"
        assert morsel["max-age"] == 30 * 24 * 60 * 60
        # __Host-: no sibling host on the registrable domain (Keycloak's lives on one) can shadow it.
        assert name.startswith("__Host-") and morsel["path"] == "/" and not morsel["domain"]


def test_a_failed_refresh_is_public_and_drops_both_cookies(asked: Asked) -> None:
    expired, _ = _tokens(lifetime=-1)
    viewer, response = _served({_COOKIES.access: expired, _COOKIES.refresh: "revoked"})
    assert viewer == Public()
    assert response.cookies[_COOKIES.access].value == ""
    assert response.cookies[_COOKIES.refresh].value == ""


def test_no_token_cookies_touch_nothing(asked: Asked) -> None:
    viewer, response = _served({})
    assert viewer == Public()
    assert _refreshed(asked) == []
    assert not response.cookies


def test_one_request_refreshes_at_most_once(asked: Asked) -> None:
    _, refresh = _tokens()
    _served({_COOKIES.refresh: refresh})
    assert _refreshed(asked) == [refresh]


def test_a_view_that_sets_its_own_token_cookies_wins(asked: Asked) -> None:
    """Logout deletes the cookies; a refresh during the same request may not bring them back."""
    _, refresh = _tokens()

    def logout_like(_request: HttpRequest) -> HttpResponse:
        response = HttpResponse()
        delete_token_cookies(response)
        return response

    _, response = _served({_COOKIES.refresh: refresh}, logout_like)
    assert response.cookies[_COOKIES.access].value == ""
    assert response.cookies[_COOKIES.refresh].value == ""


def test_an_oversized_access_token_is_logged(
    asked: Asked, caplog: pytest.LogCaptureFixture
) -> None:
    """Browsers drop a cookie over 4 kB without a word; every request would then refresh."""
    _, refresh = _tokens({**_ARCHIVIST, "padding": "x" * 4000})
    with caplog.at_level(logging.WARNING, logger="bundesarchiv.app.web.viewers"):
        _, response = _served({_COOKIES.refresh: refresh})
    assert str(len(response.cookies[_COOKIES.access].value)) in caplog.text
