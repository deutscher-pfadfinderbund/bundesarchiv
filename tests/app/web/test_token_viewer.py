"""OIDC viewers from the token cookies (ADR 0018): check, refresh, and what the response carries.

The realm is faked at the two names ``viewers`` reaches it by (``verify_access``, ``refresh``);
``viewer_of`` and ``TokenCookieMiddleware`` run for real.
"""

import logging
from collections.abc import Callable, Mapping

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from bundesarchiv.app.web import viewers
from bundesarchiv.app.web.keycloak import Tokens
from bundesarchiv.app.web.viewers import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    TokenCookieMiddleware,
    delete_token_cookies,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_ARCHIVIST: Mapping[str, object] = {
    "preferred_username": "anna",
    "realm_access": {"roles": ["Bundesarchiv"]},
}
_MEMBER: Mapping[str, object] = {"groups": ["/DPB/Bundesführung"]}
_RENEWED = Tokens(access="access-2", refresh="refresh-2", claims=_ARCHIVIST, id_token=None)


class _Realm:
    def __init__(self) -> None:
        self.valid: dict[str, Mapping[str, object]] = {}
        self.refreshable: dict[str, Tokens] = {}
        self.refreshed: list[str] = []

    def verify_access(self, token: str) -> Mapping[str, object] | None:
        return self.valid.get(token)

    def refresh(self, token: str) -> Tokens | None:
        self.refreshed.append(token)
        return self.refreshable.get(token)


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch) -> _Realm:
    fake = _Realm()
    monkeypatch.setattr(viewers, "verify_access", fake.verify_access)
    monkeypatch.setattr(viewers, "refresh", fake.refresh)
    return fake


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


def test_a_valid_access_token_is_the_viewer(realm: _Realm) -> None:
    realm.valid["access-1"] = _ARCHIVIST
    viewer, response = _served({ACCESS_COOKIE: "access-1", REFRESH_COOKIE: "refresh-1"})
    assert viewer == Archivist(username="anna")
    assert realm.refreshed == []
    assert not response.cookies


def test_groups_come_from_the_token(realm: _Realm) -> None:
    realm.valid["access-1"] = _MEMBER
    viewer, _ = _served({ACCESS_COOKIE: "access-1"})
    assert viewer == Member(groups=("/DPB/Bundesführung",))


@pytest.mark.parametrize(
    "cookies",
    [
        pytest.param({ACCESS_COOKIE: "expired", REFRESH_COOKIE: "refresh-1"}, id="expired-access"),
        pytest.param({REFRESH_COOKIE: "refresh-1"}, id="no-access-cookie"),
    ],
)
def test_a_refresh_renews_the_viewer_and_both_cookies(
    realm: _Realm, cookies: Mapping[str, str]
) -> None:
    realm.refreshable["refresh-1"] = _RENEWED
    viewer, response = _served(cookies)
    assert viewer == Archivist(username="anna")
    assert response.cookies[ACCESS_COOKIE].value == "access-2"
    assert response.cookies[REFRESH_COOKIE].value == "refresh-2"
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        morsel = response.cookies[name]
        assert morsel["httponly"] and morsel["secure"] and morsel["samesite"] == "Lax"
        assert morsel["max-age"] == 30 * 24 * 60 * 60
        # __Host-: no sibling host on the registrable domain (Keycloak's lives on one) can shadow it.
        assert name.startswith("__Host-") and morsel["path"] == "/" and not morsel["domain"]


def test_a_failed_refresh_is_public_and_drops_both_cookies(realm: _Realm) -> None:
    viewer, response = _served({ACCESS_COOKIE: "expired", REFRESH_COOKIE: "revoked"})
    assert viewer == Public()
    assert response.cookies[ACCESS_COOKIE].value == ""
    assert response.cookies[REFRESH_COOKIE].value == ""


def test_no_token_cookies_touch_nothing(realm: _Realm) -> None:
    viewer, response = _served({})
    assert viewer == Public()
    assert realm.refreshed == []
    assert not response.cookies


def test_one_request_refreshes_at_most_once(realm: _Realm) -> None:
    realm.refreshable["refresh-1"] = _RENEWED
    _served({REFRESH_COOKIE: "refresh-1"})
    assert realm.refreshed == ["refresh-1"]


def test_a_view_that_sets_its_own_token_cookies_wins(realm: _Realm) -> None:
    """Logout deletes the cookies; a refresh during the same request may not bring them back."""
    realm.refreshable["refresh-1"] = _RENEWED

    def logout_like(_request: HttpRequest) -> HttpResponse:
        response = HttpResponse()
        delete_token_cookies(response)
        return response

    _, response = _served({REFRESH_COOKIE: "refresh-1"}, logout_like)
    assert response.cookies[ACCESS_COOKIE].value == ""
    assert response.cookies[REFRESH_COOKIE].value == ""


def test_an_oversized_access_token_is_logged(
    realm: _Realm, caplog: pytest.LogCaptureFixture
) -> None:
    """Browsers drop a cookie over 4 kB without a word; every request would then refresh."""
    realm.refreshable["refresh-1"] = Tokens(
        access="x" * 4001, refresh="refresh-2", claims=_ARCHIVIST, id_token=None
    )
    with caplog.at_level(logging.WARNING, logger="bundesarchiv.app.web.viewers"):
        _served({REFRESH_COOKIE: "refresh-1"})
    assert "4001" in caplog.text
