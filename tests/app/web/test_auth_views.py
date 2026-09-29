"""The OIDC login surface: ``/login``, ``/oidc/callback``, ``POST /logout`` (ADR 0018).

Keycloak is the ONE thing faked here — through the seams ``auth_views`` and ``viewers`` reach it by
(``authorization_url`` / ``fetch_tokens`` / ``logout_url``, ``verify_access`` / ``refresh``),
monkeypatched as module names the way the web suite stubs its other genuine external boundaries.
Everything else is real: the signed transient cookie, the token cookies, ``viewer_of``, and the
archivist route gate the round trip ends on — the last one is what proves the login actually
authenticated somebody.
"""

from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from django.core import signing
from django.test import Client, override_settings
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import Corpus

from bundesarchiv.app.web import auth_views, viewers
from bundesarchiv.app.web.auth_views import STATE_COOKIE, safe_next
from bundesarchiv.app.web.keycloak import Tokens
from bundesarchiv.app.web.viewers import ACCESS_COOKIE, REFRESH_COOKIE

_KEY = "test-viewer-signing-key"

_ARCHIVIST_CLAIMS: Mapping[str, object] = {
    "preferred_username": "anna.schmidt",
    "realm_access": {"roles": ["Bundesarchiv"]},
}
_MEMBER_CLAIMS: Mapping[str, object] = {
    "sub": "u1",
    "preferred_username": "max.mitglied",
    "groups": ["vorstand"],
}

_ARCHIVIST_TOKENS = Tokens(
    access="access-archivist",
    refresh="refresh-archivist",
    claims=_ARCHIVIST_CLAIMS,
    id_token="id-a",
)
_MEMBER_TOKENS = Tokens(
    access="access-member", refresh="refresh-member", claims=_MEMBER_CLAIMS, id_token="id-m"
)

_AUTHORIZE = "https://auth.example/realms/dpb/protocol/openid-connect/auth"
_END_SESSION = "https://auth.example/realms/dpb/protocol/openid-connect/logout"


class _FakeKeycloak:
    """An in-memory stand-in for the realm: it records what the views hand it and answers what the
    test told it to. ``authorize``/``logout``/``tokens`` set to ``None`` model an unconfigured or
    unreachable realm — the seams' documented failure answer. ``verify_access`` accepts exactly the
    access token it handed out, so the round trip authenticates through the real ``viewer_of``."""

    def __init__(self, *, tokens: Tokens | None, authorize: str | None, logout: str | None) -> None:
        self.tokens = tokens
        self.authorize = authorize
        self.logout = logout
        self.seen: dict[str, str] = {}
        self.logout_refresh: str | None = None
        self.refreshed_to: Tokens | None = None

    def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str | None:
        self.seen |= {"state": state, "nonce": nonce, "redirect_uri": redirect_uri}
        return None if self.authorize is None else f"{self.authorize}?state={state}"

    def fetch_tokens(self, *, code: str, nonce: str, redirect_uri: str) -> Tokens | None:
        self.seen |= {"code": code, "callback_nonce": nonce, "callback_redirect": redirect_uri}
        return self.tokens

    def verify_access(self, token: str) -> Mapping[str, object] | None:
        return self.tokens.claims if self.tokens and token == self.tokens.access else None

    def refresh(self, _token: str) -> Tokens | None:
        return self.refreshed_to

    def logout_url(self, *, refresh_token: str | None, post_logout_redirect_uri: str) -> str | None:
        self.logout_refresh = refresh_token
        self.seen |= {"post_logout": post_logout_redirect_uri}
        if self.logout is None:
            return None
        return f"{self.logout}?redirect_uri={post_logout_redirect_uri}"


@pytest.fixture
def keycloak(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeKeycloak]:
    """The faked realm, wired into the seams ``auth_views`` and ``viewers`` reach it by, with a
    signing key configured."""
    fake = _FakeKeycloak(tokens=_ARCHIVIST_TOKENS, authorize=_AUTHORIZE, logout=_END_SESSION)
    monkeypatch.setattr(auth_views, "authorization_url", fake.authorization_url)
    monkeypatch.setattr(auth_views, "fetch_tokens", fake.fetch_tokens)
    monkeypatch.setattr(auth_views, "logout_url", fake.logout_url)
    monkeypatch.setattr(viewers, "verify_access", fake.verify_access)
    monkeypatch.setattr(viewers, "refresh", fake.refresh)
    with override_settings(VIEWER_SIGNING_KEY=_KEY):
        yield fake


def _login(client: Client, **params: str) -> Any:
    return client.get("/login", params)


def _callback(client: Client, **params: str) -> Any:
    return client.get("/oidc/callback", params)


# --- the round trip -------------------------------------------------------------------------------


def test_a_full_login_authenticates_on_the_archivist_gate(
    corpus: Corpus, keycloak: _FakeKeycloak
) -> None:
    """The whole point, end to end: an anonymous client starts at ``/login``, comes back through the
    callback, and the cookie it now carries opens an archivist-only route."""
    client = Client()
    assert client.get("/artikel/neu").status_code == 404  # nobody yet

    start = _login(client, next="/artikel/neu")
    assert start.status_code == 302
    assert start["Location"].startswith(_AUTHORIZE)

    landing = _callback(client, code="the-code", state=keycloak.seen["state"])
    assert landing.status_code == 302
    assert landing["Location"] == "/artikel/neu"
    assert client.get("/artikel/neu").status_code == 200


def test_the_callback_replays_the_nonce_the_authorize_request_carried(
    keycloak: _FakeKeycloak,
) -> None:
    """The nonce binding: the value handed to the token exchange is the one this browser's authorize
    request carried, so an ID token minted for a different login cannot be replayed into this one."""
    client = Client()
    _login(client)
    _callback(client, code="c", state=keycloak.seen["state"])
    assert keycloak.seen["callback_nonce"] == keycloak.seen["nonce"]
    assert keycloak.seen["callback_redirect"] == keycloak.seen["redirect_uri"]
    assert keycloak.seen["redirect_uri"] == "http://testserver/oidc/callback"


def test_the_callback_leaves_both_token_cookies(
    keycloak: _FakeKeycloak,
) -> None:
    keycloak.tokens = _MEMBER_TOKENS
    client = Client()
    _login(client)
    _callback(client, code="c", state=keycloak.seen["state"])
    assert client.cookies[ACCESS_COOKIE].value == "access-member"
    assert client.cookies[REFRESH_COOKIE].value == "refresh-member"
    assert client.get("/artikel/neu").status_code == 404  # a Member, not an Archivist


def test_the_transient_state_cookie_is_dropped_at_the_callback(keycloak: _FakeKeycloak) -> None:
    """One state cookie serves one login; the callback clears it, so a replayed callback URL finds
    no state to match against."""
    client = Client()
    _login(client)
    state = keycloak.seen["state"]
    _callback(client, code="c", state=state)
    assert client.cookies[STATE_COOKIE].value == ""
    assert_denied(_callback(client, code="c", state=state), "replayed callback")


# --- /login ---------------------------------------------------------------------------------------


def test_login_plants_a_signed_state_cookie(keycloak: _FakeKeycloak) -> None:
    client = Client()
    response = _login(client)
    cookie = response.cookies[STATE_COOKIE]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
    # __Host-: no sibling host on the registrable domain (Keycloak's own lives on one) can shadow
    # this cookie with a Domain=-scoped one of the same name.
    assert STATE_COOKIE.startswith("__Host-")
    assert cookie["path"] == "/" and not cookie["domain"]
    assert (
        signing.loads(cookie.value, key=_KEY, salt="oidc-state")["state"]
        == (keycloak.seen["state"])
    )


def test_login_falls_closed_without_a_signing_key(keycloak: _FakeKeycloak) -> None:
    """No ``VIEWER_SIGNING_KEY`` = no cookie anybody could verify, so the login never starts."""
    with override_settings(VIEWER_SIGNING_KEY=None):
        response = _login(Client())
    assert_denied(response, "login without a signing key")
    assert STATE_COOKIE not in response.cookies


def test_login_falls_closed_when_the_realm_is_unreachable(keycloak: _FakeKeycloak) -> None:
    keycloak.authorize = None
    response = _login(Client())
    assert_denied(response, "login with no authorize endpoint")
    assert STATE_COOKIE not in response.cookies


def test_login_rejects_a_post(keycloak: _FakeKeycloak) -> None:
    assert_denied(Client().post("/login"), "POST /login")


# --- the callback's deny rows ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "params"),
    [
        ("no code", {"state": "-"}),
        ("empty code", {"code": "", "state": "-"}),
        ("no state", {"code": "c"}),
    ],
)
def test_callback_denies_a_bad_request(
    keycloak: _FakeKeycloak, label: str, params: dict[str, str]
) -> None:
    client = Client()
    _login(client)
    if params.get("state") == "-":
        params = params | {"state": keycloak.seen["state"]}
    response = _callback(client, **params)
    assert_denied(response, label)
    assert ACCESS_COOKIE not in response.cookies


@pytest.mark.parametrize("state", ["not-the-one", "ü"])
def test_a_state_that_does_not_match_restarts_the_login(
    keycloak: _FakeKeycloak, state: str
) -> None:
    """Two tabs, one state cookie: the second ``/login`` overwrote it, so the first tab's callback
    can never match. With a VERIFIED transient in hand this is a stale login, not an attack — the
    visitor is sent back through the flow to the page they wanted instead of onto a blank 404.

    The non-ASCII row rides the same path: ``compare_digest`` refuses non-ASCII ``str``, so an
    unencoded comparison would answer this callback with a 500."""
    client = Client()
    _login(client, next="/artikel/neu")
    response = _callback(client, code="c", state=state)
    assert response.status_code == 302
    assert response["Location"] == "/login?next=%2Fartikel%2Fneu"
    assert ACCESS_COOKIE not in response.cookies


def test_callback_denies_without_the_state_cookie(keycloak: _FakeKeycloak) -> None:
    """A callback nobody's ``/login`` started: no transient cookie, so no state to compare."""
    response = _callback(Client(), code="c", state="whatever")
    assert_denied(response, "callback with no state cookie")
    assert ACCESS_COOKIE not in response.cookies


def test_callback_denies_a_tampered_state_cookie(keycloak: _FakeKeycloak) -> None:
    client = Client()
    _login(client)
    signed = client.cookies[STATE_COOKIE].value
    client.cookies[STATE_COOKIE] = signed[:-1] + ("a" if signed[-1] != "a" else "b")
    assert_denied(_callback(client, code="c", state=keycloak.seen["state"]), "tampered state")


def test_callback_denies_a_state_cookie_signed_with_another_key(keycloak: _FakeKeycloak) -> None:
    client = Client()
    client.cookies[STATE_COOKIE] = signing.dumps(
        {"state": "s", "nonce": "n", "next": "/"}, key="another-key", salt="oidc-state"
    )
    assert_denied(_callback(client, code="c", state="s"), "state cookie under a foreign key")


def test_callback_denies_an_expired_state_cookie(
    keycloak: _FakeKeycloak, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Client()
    _login(client)
    monkeypatch.setattr(auth_views, "_STATE_MAX_AGE", -1)
    assert_denied(_callback(client, code="c", state=keycloak.seen["state"]), "expired state")


def test_callback_denies_when_the_token_exchange_fails(keycloak: _FakeKeycloak) -> None:
    """Keycloak refused the code, or the ID token did not validate — the seam answers ``None``."""
    keycloak.tokens = None
    client = Client()
    _login(client)
    response = _callback(client, code="stale", state=keycloak.seen["state"])
    assert_denied(response, "failed token exchange")
    assert ACCESS_COOKIE not in response.cookies


def test_callback_rejects_a_post(keycloak: _FakeKeycloak) -> None:
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
        "artikel/neu",
        "",
    ],
)
def test_a_hostile_next_never_becomes_the_landing_page(
    keycloak: _FakeKeycloak, hostile: str
) -> None:
    """An off-site ``?next=`` is dropped at ``/login``, so the callback can only ever land on the
    workbench — the redirect never leaves this origin."""
    assert safe_next(hostile) is None
    client = Client()
    _login(client, next=hostile)
    landing = _callback(client, code="c", state=keycloak.seen["state"])
    assert landing["Location"] == "/"


@pytest.mark.parametrize(
    "path", ["/", "/artikel/neu", "/?q=sommer&seite=2", "/artikel/01KX7YT9E3VX0CP3A5Q49RZMWK"]
)
def test_a_same_origin_next_is_kept(keycloak: _FakeKeycloak, path: str) -> None:
    assert safe_next(path) == path
    client = Client()
    _login(client, next=path)
    assert _callback(client, code="c", state=keycloak.seen["state"])["Location"] == path


def test_safe_next_of_nothing_is_nothing() -> None:
    assert safe_next(None) is None


# --- logout ---------------------------------------------------------------------------------------


def test_logout_hands_the_refresh_cookie_on_and_clears_both_cookies(
    keycloak: _FakeKeycloak,
) -> None:
    """Shared-computer ruling (ADR 0018): the cookies go AND the browser is sent through Keycloak's
    end-session endpoint, with what it needs to end the Keycloak session unasked."""
    client = Client()
    _login(client)
    _callback(client, code="c", state=keycloak.seen["state"])
    assert client.get("/artikel/neu").status_code == 200

    response = client.post("/logout")
    assert response.status_code == 302
    assert response["Location"].startswith(_END_SESSION)
    assert keycloak.logout_refresh == "refresh-archivist"
    assert keycloak.seen["post_logout"] == "http://testserver/"
    assert client.cookies[ACCESS_COOKIE].value == ""
    assert client.cookies[REFRESH_COOKIE].value == ""


def test_logout_clears_the_cookies_even_with_no_realm_to_return_through(
    keycloak: _FakeKeycloak,
) -> None:
    keycloak.logout = None
    client = Client()
    _login(client)
    _callback(client, code="c", state=keycloak.seen["state"])
    response = client.post("/logout")
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.cookies[ACCESS_COOKIE].value == ""
    assert client.cookies[REFRESH_COOKIE].value == ""


def test_logout_without_token_cookies_still_clears_and_redirects(keycloak: _FakeKeycloak) -> None:
    response = Client().post("/logout")
    assert response.status_code == 302
    assert keycloak.logout_refresh is None
    assert response.cookies[ACCESS_COOKIE].value == ""


def test_a_refresh_through_the_real_middleware_stack_renews_both_cookies(
    keycloak: _FakeKeycloak,
) -> None:
    """The deployed MIDDLEWARE, not a hand-built one: a browser holding only a refresh cookie opens
    the archivist route and gets both renewed cookies back."""
    keycloak.refreshed_to = _ARCHIVIST_TOKENS
    client = Client()
    client.cookies[REFRESH_COOKIE] = "refresh-old"
    response = client.get("/artikel/neu")
    assert response.status_code == 200
    assert response.cookies[ACCESS_COOKIE].value == "access-archivist"
    assert response.cookies[REFRESH_COOKIE].value == "refresh-archivist"


def test_a_dead_refresh_cookie_is_cleared_on_the_way_to_the_login(
    keycloak: _FakeKeycloak,
) -> None:
    client = Client()
    client.cookies[REFRESH_COOKIE] = "revoked"
    response = client.get("/artikel/neu")
    assert response.status_code == 302
    assert response.cookies[ACCESS_COOKIE].value == ""
    assert response.cookies[REFRESH_COOKIE].value == ""


def test_logout_rejects_a_get(keycloak: _FakeKeycloak) -> None:
    assert_denied(Client().get("/logout"), "GET /logout")
