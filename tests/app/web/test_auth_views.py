"""The OIDC login surface: ``/login``, ``/oidc/callback``, ``POST /logout`` (ADR 0018).

The login runs on the dev realm (``BUNDESARCHIV_REALM``), which mints the code a login answers with
and checks the tokens it issued. Everything else is real: the signed transient cookie, the token
cookies, ``viewer_of``, and the archivist route gate the round trip ends on — the last one is what
proves the login actually authenticated somebody.
"""

import time
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.core import signing
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied, assert_door
from tests.app.web._fixtures import (
    VIEWER_KEY,
    Asked,
    Corpus,
    RecordingRealm,
    dev_realm_settings,
)

from bundesarchiv.app.web.auth_views import safe_next
from bundesarchiv.app.web.dev_realm import AUTHORIZE_PATH, DevRealm
from bundesarchiv.app.web.viewers import login_cookies

#: The test settings serve https, so these are the ``__Host-`` names.
_COOKIES = login_cookies()

_ARCHIVIST_CLAIMS: Mapping[str, object] = {
    "preferred_username": "anna.schmidt",
    "realm_access": {"roles": ["Bundesarchiv"]},
}
_MEMBER_CLAIMS: Mapping[str, object] = {
    "sub": "u1",
    "preferred_username": "max.mitglied",
    "groups": ["vorstand"],
}


@pytest.fixture
def asked() -> Iterator[Asked]:
    """What the dev realm the login runs on is asked, with both signing keys configured."""
    calls: Asked = []
    with override_settings(**dev_realm_settings(RecordingRealm(calls))):
        yield calls


def _last(asked: Asked, operation: str) -> dict[str, str | None]:
    return next(args for name, args in reversed(asked) if name == operation)


def _login(client: Client, **params: str) -> Any:
    return client.get("/login", params)


def _callback(client: Client, **params: str) -> Any:
    return client.get("/oidc/callback", params)


def _authorized(
    client: Client, claims: Mapping[str, object] = _ARCHIVIST_CLAIMS, **params: str
) -> dict[str, str]:
    """Start a login and answer it as the realm's login page does: the ``code`` for ``claims``,
    bound to the login's nonce, and its ``state``."""
    query = parse_qs(urlsplit(_login(client, **params)["Location"]).query)
    code = DevRealm().mint_code(claims, nonce=query["nonce"][0])
    assert code is not None
    return {"code": code, "state": query["state"][0]}


def _logged_in(client: Client, claims: Mapping[str, object] = _ARCHIVIST_CLAIMS) -> None:
    _callback(client, **_authorized(client, claims))


# --- the round trip -------------------------------------------------------------------------------


def test_a_full_login_authenticates_on_the_archivist_gate(corpus: Corpus, asked: Asked) -> None:
    client = Client()
    assert client.get("/articles/new").status_code == 404  # nobody yet

    start = _login(client, next="/articles/new")
    assert start.status_code == 302
    assert urlsplit(start["Location"]).path == AUTHORIZE_PATH

    landing = _callback(client, **_authorized(client, next="/articles/new"))
    assert landing.status_code == 302
    assert landing["Location"] == "/articles/new"
    assert client.get("/articles/new").status_code == 200


def test_the_callback_replays_the_nonce_the_authorize_request_carried(asked: Asked) -> None:
    """The nonce binding: the value handed to the token exchange is the one this browser's authorize
    request carried, so an ID token minted for a different login cannot be replayed into this one."""
    _logged_in(Client())
    authorize, exchange = _last(asked, "authorization_url"), _last(asked, "fetch_tokens")
    assert exchange["nonce"] == authorize["nonce"]
    assert exchange["redirect_uri"] == authorize["redirect_uri"]
    assert authorize["redirect_uri"] == "http://testserver/oidc/callback"


def test_the_callback_leaves_both_token_cookies(asked: Asked) -> None:
    client = Client()
    _logged_in(client, _MEMBER_CLAIMS)
    claims = DevRealm().verify_access(client.cookies[_COOKIES.access].value)
    assert claims is not None
    assert claims["groups"] == ["vorstand"]
    assert DevRealm().refresh(client.cookies[_COOKIES.refresh].value) is not None
    assert client.get("/articles/new").status_code == 404  # a Member, not an Archivist


def test_the_transient_state_cookie_is_dropped_at_the_callback(asked: Asked) -> None:
    """One state cookie serves one login; the callback clears it, so a replayed callback URL finds
    no state to match against."""
    client = Client()
    answer = _authorized(client)
    _callback(client, **answer)
    assert client.cookies[_COOKIES.state].value == ""
    assert_denied(_callback(client, **answer), "replayed callback")


# --- /login ---------------------------------------------------------------------------------------


def test_login_plants_a_signed_state_cookie(asked: Asked) -> None:
    client = Client()
    response = _login(client)
    cookie = response.cookies[_COOKIES.state]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
    # __Host-: no sibling host on the registrable domain (Keycloak's own lives on one) can shadow
    # this cookie with a Domain=-scoped one of the same name.
    assert _COOKIES.state.startswith("__Host-")
    assert cookie["path"] == "/" and not cookie["domain"]
    assert (
        signing.loads(cookie.value, key=VIEWER_KEY, salt="oidc-state")["state"]
        == _last(asked, "authorization_url")["state"]
    )


def test_login_falls_closed_without_a_signing_key(asked: Asked) -> None:
    """No ``VIEWER_SIGNING_KEY`` = no cookie anybody could verify, so the login never starts."""
    with override_settings(VIEWER_SIGNING_KEY=None):
        response = _login(Client())
    assert_denied(response, "login without a signing key")
    assert _COOKIES.state not in response.cookies


def test_login_falls_closed_when_the_realm_answers_nothing(asked: Asked) -> None:
    with override_settings(DEV_VIEWER_SIGNING_KEY=None):
        response = _login(Client())
    assert_denied(response, "login with no authorize endpoint")
    assert _COOKIES.state not in response.cookies


def test_login_rejects_a_post(asked: Asked) -> None:
    assert_denied(Client().post("/login"), "POST /login")


# --- the callback's deny rows ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "dropped"),
    [("no code", {"code": None}), ("empty code", {"code": ""}), ("no state", {"state": None})],
)
def test_callback_denies_a_bad_request(
    asked: Asked, label: str, dropped: dict[str, str | None]
) -> None:
    client = Client()
    answer = _authorized(client) | dropped
    response = _callback(client, **{k: v for k, v in answer.items() if v is not None})
    assert_denied(response, label)
    assert _COOKIES.access not in response.cookies


@pytest.mark.parametrize("state", ["not-the-one", "ü"])
def test_a_state_that_does_not_match_restarts_the_login(asked: Asked, state: str) -> None:
    """Two tabs, one state cookie: the second ``/login`` overwrote it, so the first tab's callback
    can never match. With a VERIFIED transient in hand this is a stale login, not an attack — the
    visitor is sent back through the flow to the page they wanted instead of onto a blank 404.

    The non-ASCII row rides the same path: ``compare_digest`` refuses non-ASCII ``str``, so an
    unencoded comparison would answer this callback with a 500."""
    client = Client()
    answer = _authorized(client, next="/articles/new")
    response = _callback(client, code=answer["code"], state=state)
    assert response.status_code == 302
    assert response["Location"] == "/login?next=%2Farticles%2Fnew"
    assert _COOKIES.access not in response.cookies


def test_callback_denies_without_the_state_cookie(asked: Asked) -> None:
    """A callback nobody's ``/login`` started: no transient cookie, so no state to compare."""
    answer = _authorized(Client())
    response = _callback(Client(), **answer)
    assert_denied(response, "callback with no state cookie")
    assert _COOKIES.access not in response.cookies


def test_callback_denies_a_tampered_state_cookie(asked: Asked) -> None:
    client = Client()
    answer = _authorized(client)
    signed = client.cookies[_COOKIES.state].value
    client.cookies[_COOKIES.state] = signed[:-1] + ("a" if signed[-1] != "a" else "b")
    assert_denied(_callback(client, **answer), "tampered state")


def _state_cookie(*, key: str, issued: float) -> str:
    """A state cookie for the login ``s``/``n`` as ``/login`` writes it, signed with ``key`` at
    ``issued``."""

    class _Issued(signing.TimestampSigner):
        def timestamp(self) -> str:
            return signing.b62_encode(int(issued))

    return _Issued(key=key, salt="oidc-state").sign_object(
        {"state": "s", "nonce": "n", "next": "/"}
    )


@pytest.mark.parametrize(
    ("label", "key", "age"),
    [
        ("state cookie under a foreign key", "another-key", 0),
        ("expired state", VIEWER_KEY, 24 * 60 * 60),
    ],
)
def test_callback_denies_a_state_cookie_it_cannot_trust(
    asked: Asked, label: str, key: str, age: int
) -> None:
    """The login it names is otherwise complete: the code is bound to that cookie's nonce."""
    client = Client()
    client.cookies[_COOKIES.state] = _state_cookie(key=key, issued=time.time() - age)
    code = DevRealm().mint_code(_ARCHIVIST_CLAIMS, nonce="n")
    assert code is not None
    response = _callback(client, code=code, state="s")
    assert_denied(response, label)
    assert _COOKIES.access not in response.cookies


def test_callback_denies_when_the_token_exchange_fails(asked: Asked) -> None:
    """A code the realm refuses: here one minted for another login's nonce."""
    client = Client()
    answer = _authorized(client)
    stale = DevRealm().mint_code(_ARCHIVIST_CLAIMS, nonce="another-login")
    assert stale is not None
    response = _callback(client, code=stale, state=answer["state"])
    assert_denied(response, "failed token exchange")
    assert _COOKIES.access not in response.cookies


def test_callback_rejects_a_post(asked: Asked) -> None:
    assert_denied(Client().post("/oidc/callback"), "POST /oidc/callback")


# --- ?next= : the open-redirect whitelist ---------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example/steal",
        "http://evil.example",
        "//evil.example",
        "///evil.example",
        "/\\evil.example",
        "\\\\evil.example",
        "javascript:alert(1)",
        "/artikel\\..\\evil",
        "/artikel\r\nSet-Cookie: x=1",
        "/artikel\nx",
        "articles/new",
        "",
    ],
)
def test_a_hostile_next_never_becomes_the_landing_page(asked: Asked, hostile: str) -> None:
    """An off-site ``?next=`` is dropped at ``/login``, so the callback can only ever land on the
    workbench — the redirect never leaves this origin."""
    assert safe_next(hostile) is None
    client = Client()
    landing = _callback(client, **_authorized(client, next=hostile))
    assert landing["Location"] == "/"


@pytest.mark.parametrize(
    "path", ["/", "/articles/new", "/?q=sommer&page=2", "/articles/01KX7YT9E3VX0CP3A5Q49RZMWK"]
)
def test_a_same_origin_next_is_kept(asked: Asked, path: str) -> None:
    assert safe_next(path) == path
    client = Client()
    assert _callback(client, **_authorized(client, next=path))["Location"] == path


def test_safe_next_of_nothing_is_nothing() -> None:
    assert safe_next(None) is None


# --- logout ---------------------------------------------------------------------------------------


def test_logout_hands_the_refresh_cookie_on_and_clears_both_cookies(asked: Asked) -> None:
    """Shared-computer ruling (ADR 0018): the cookies go AND the browser is sent through the realm's
    end-session step, with what it needs to end the realm's session unasked."""
    client = Client()
    _logged_in(client)
    assert client.get("/articles/new").status_code == 200
    refresh_token = client.cookies[_COOKIES.refresh].value

    response = client.post("/logout")
    assert response.status_code == 302
    logout = _last(asked, "logout_url")
    assert logout == {
        "refresh_token": refresh_token,
        "post_logout_redirect_uri": "http://testserver/",
    }
    assert response["Location"] == "http://testserver/"
    assert client.cookies[_COOKIES.access].value == ""
    assert client.cookies[_COOKIES.refresh].value == ""


def test_logout_clears_the_cookies_even_with_no_realm_to_return_through(asked: Asked) -> None:
    client = Client()
    _logged_in(client)
    with override_settings(DEV_VIEWER_SIGNING_KEY=None):
        response = client.post("/logout")
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.cookies[_COOKIES.access].value == ""
    assert client.cookies[_COOKIES.refresh].value == ""


def test_logout_without_token_cookies_still_clears_and_redirects(asked: Asked) -> None:
    response = Client().post("/logout")
    assert response.status_code == 302
    assert _last(asked, "logout_url")["refresh_token"] is None
    assert response.cookies[_COOKIES.access].value == ""


def test_a_refresh_through_the_real_middleware_stack_renews_both_cookies(asked: Asked) -> None:
    """The deployed MIDDLEWARE, not a hand-built one: a browser holding only a refresh cookie opens
    the archivist route and gets both renewed cookies back."""
    tokens = DevRealm().mint_tokens(_ARCHIVIST_CLAIMS)
    assert tokens is not None
    client = Client()
    client.cookies[_COOKIES.refresh] = tokens.refresh
    response = client.get("/articles/new")
    assert response.status_code == 200
    renewed = DevRealm().verify_access(response.cookies[_COOKIES.access].value)
    assert renewed is not None
    assert renewed["preferred_username"] == "anna.schmidt"
    assert DevRealm().refresh(response.cookies[_COOKIES.refresh].value) is not None


def test_a_dead_refresh_cookie_is_cleared_on_the_way_to_the_door(asked: Asked) -> None:
    client = Client()
    client.cookies[_COOKIES.refresh] = "revoked"
    response = client.get("/articles/new")
    assert_door(response, "/articles/new")
    assert response.cookies[_COOKIES.access].value == ""
    assert response.cookies[_COOKIES.refresh].value == ""


def test_logout_rejects_a_get(asked: Asked) -> None:
    assert_denied(Client().get("/logout"), "GET /logout")


# --- the https switch (ADR 0025) ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("secure", "names"),
    [
        (True, ("__Host-access", "__Host-refresh", "__Host-oidc_state")),
        (False, ("bundesarchiv_access", "bundesarchiv_refresh", "bundesarchiv_oidc_state")),
    ],
    ids=["https", "plain-http"],
)
def test_every_login_cookie_follows_the_https_switch(
    corpus: Corpus, asked: Asked, secure: bool, names: tuple[str, str, str]
) -> None:
    """Every login cookie a response sets or deletes, at login, callback, refresh and logout."""
    refresh = names[1]
    with override_settings(CSRF_COOKIE_SECURE=secure):
        client = Client()
        start = _login(client)
        query = parse_qs(urlsplit(start["Location"]).query)
        code = DevRealm().mint_code(_ARCHIVIST_CLAIMS, nonce=query["nonce"][0])
        assert code is not None
        callback = _callback(client, code=code, state=query["state"][0])
        assert callback["Location"] == "/"  # the state cookie was read under its name
        renewing = Client()
        renewing.cookies[refresh] = client.cookies[refresh].value
        renewed = renewing.get("/articles/new")
        assert renewed.status_code == 200  # ...and the refresh cookie under its own
        dead = Client()
        dead.cookies[refresh] = "revoked"
        dropped = dead.get("/articles/new")
        logout = client.post("/logout")
    sent = [
        morsel
        for response in (start, callback, renewed, dropped, logout)
        for morsel in response.cookies.values()
        if morsel.key != settings.CSRF_COOKIE_NAME
    ]
    assert {morsel.key for morsel in sent} == set(names)
    assert all(bool(morsel["secure"]) is secure for morsel in sent)
