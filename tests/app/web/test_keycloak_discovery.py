"""What the Keycloak adapter decides for itself (ADR 0018): its caches and the URLs it builds.

The realm itself is deliberately not suite-tested (ADR 0018, "Testing") — a fake can only encode our
own assumptions about Keycloak. The CACHE is ours, and its failure mode is not a refused login but a
dead worker: a remembered ``None`` would answer every later login in that process, and with the
anonymous gate on, every request then loops through a login that 404s.
"""

from collections.abc import Iterator, Mapping
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from joserfc.jwk import KeySet, RSAKey
from pytest_django.fixtures import Settings

from bundesarchiv.app.web import keycloak

_ISSUER = "https://auth.example/realms/dpb"
_LOGOUT = f"{_ISSUER}/protocol/openid-connect/logout"
_JWKS_URI = f"{_ISSUER}/protocol/openid-connect/certs"
_DOCUMENT: Mapping[str, object] = {
    "authorization_endpoint": f"{_ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{_ISSUER}/protocol/openid-connect/token",
}
_PUBLIC = RSAKey.generate_key(2048).as_dict(private=False)
_KEY_SET: Mapping[str, object] = {"keys": [{**_PUBLIC, "kid": "signing-2026-08"}]}
_ROTATED: Mapping[str, object] = {"keys": [{**_PUBLIC, "kid": "signing-2026-09"}]}


def _kids(keys: KeySet | None) -> set[str | None] | None:
    return None if keys is None else {key.kid for key in keys}


class _Realm:
    """The realm's HTTP endpoints as an ``httpx2.get`` stand-in — the ONE genuine external boundary
    here. ``down`` raises the connection failure a restarting realm gives; ``body`` is what it
    serves."""

    def __init__(self) -> None:
        self.down = False
        self.body: object = dict(_DOCUMENT)

    def get(self, url: str, **_: object) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("realm restarting")
        return httpx2.Response(200, json=self.body, request=httpx2.Request("GET", url))


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Realm]:
    """A realm behind the adapter, with the process-wide caches empty before and after."""
    keycloak._DOCUMENTS.clear()
    keycloak._KEY_SETS.clear()
    fake = _Realm()
    # On the httpx2 module itself: the adapter calls ``httpx2.get``, so this is the same attribute.
    monkeypatch.setattr(httpx2, "get", fake.get)
    yield fake
    keycloak._DOCUMENTS.clear()
    keycloak._KEY_SETS.clear()


def test_a_failed_discovery_is_retried_not_remembered(realm: _Realm) -> None:
    """One transient outage may not disable login for the life of the process."""
    realm.down = True
    assert keycloak._metadata(_ISSUER) is None
    realm.down = False
    assert keycloak._metadata(_ISSUER) == _DOCUMENT


def test_a_document_that_is_not_an_object_is_not_remembered(realm: _Realm) -> None:
    """The other failure answer, same rule: ``None`` now, the real document once it arrives."""
    realm.body = ["not an object"]
    assert keycloak._metadata(_ISSUER) is None
    realm.body = dict(_DOCUMENT)
    assert keycloak._metadata(_ISSUER) == _DOCUMENT


def test_a_fetched_document_outlives_the_realm(realm: _Realm) -> None:
    """The positive half: once fetched, a login no longer depends on discovery answering."""
    assert keycloak._metadata(_ISSUER) == _DOCUMENT
    realm.down = True
    assert keycloak._metadata(_ISSUER) == _DOCUMENT


def test_a_failed_key_set_fetch_is_retried_not_remembered(realm: _Realm) -> None:
    """The signing keys follow the discovery document's rule: no failure is ever cached."""
    realm.down = True
    assert keycloak._jwks(_JWKS_URI) is None
    realm.down, realm.body = False, dict(_KEY_SET)
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-08"}


def test_a_key_set_with_no_usable_key_is_not_remembered(realm: _Realm) -> None:
    realm.body = {"keys": [{"kty": "unknown"}]}
    assert keycloak._jwks(_JWKS_URI) is None
    realm.body = dict(_KEY_SET)
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-08"}


def test_a_fetched_key_set_outlives_the_realm(realm: _Realm) -> None:
    """Why the cache exists: a callback validates the ID token without a second round trip to the
    realm, serially after the token exchange it already paid for."""
    realm.body = dict(_KEY_SET)
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-08"}
    realm.down = True
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-08"}


def test_a_refresh_replaces_the_cached_key_set_only_when_it_succeeds(realm: _Realm) -> None:
    """What makes a signing-key rotation survivable — and what keeps an outage during one from
    throwing away the set that still verifies yesterday's keys."""
    realm.body = dict(_KEY_SET)
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-08"}

    realm.body = dict(_ROTATED)
    assert _kids(keycloak._jwks(_JWKS_URI, refresh=True)) == {"signing-2026-09"}
    realm.down = True
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-09"}
    assert keycloak._jwks(_JWKS_URI, refresh=True) is None
    assert _kids(keycloak._jwks(_JWKS_URI)) == {"signing-2026-09"}


@pytest.mark.parametrize(
    ("advertised", "realms_own"),
    [(_LOGOUT, {}), (f"{_LOGOUT}?tenant=1", {"tenant": ["1"]})],
    ids=["plain", "already-has-a-query"],
)
def test_the_logout_url_adds_to_whatever_the_realm_advertises(
    realm: _Realm, settings: Settings, advertised: str, realms_own: dict[str, list[str]]
) -> None:
    """An ``end_session_endpoint`` may carry a query of its own; ours joins it. Overwriting it drops
    ``post_logout_redirect_uri`` and Keycloak then leaves the SSO session up (ADR 0018)."""
    realm.body = {**_DOCUMENT, "end_session_endpoint": advertised}
    settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID = _ISSUER, "bundesarchiv"

    url = keycloak._end_session_url("https://archiv.example/", id_token_hint=None)

    assert url is not None
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == _LOGOUT
    assert parse_qs(parts.query) == {
        **realms_own,
        "client_id": ["bundesarchiv"],
        "post_logout_redirect_uri": ["https://archiv.example/"],
    }


def test_a_token_response_without_a_refresh_token_logs_nobody_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(keycloak, "verify_access", lambda token: {"sub": "u1"})
    assert keycloak._tokens_of({"access_token": "a"}) is None
    assert keycloak._tokens_of({"access_token": "a", "refresh_token": "r"}) == keycloak.Tokens(
        access="a", refresh="r", claims={"sub": "u1"}, id_token=None
    )


def test_a_token_response_whose_access_token_fails_the_check_logs_nobody_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(keycloak, "verify_access", lambda token: None)
    assert keycloak._tokens_of({"access_token": "a", "refresh_token": "r"}) is None


class _Session:
    """The realm's token endpoints as ``refresh``/``_revoke`` stand-ins; records every call."""

    def __init__(self, tokens: keycloak.Tokens | None) -> None:
        self.tokens = tokens
        self.refreshed: list[str] = []
        self.revoked: list[str] = []

    def refresh(self, refresh_token: str) -> keycloak.Tokens | None:
        self.refreshed.append(refresh_token)
        return self.tokens

    def revoke(self, refresh_token: str) -> None:
        self.revoked.append(refresh_token)


def _logout_realm(
    realm: _Realm,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tokens: keycloak.Tokens | None,
) -> _Session:
    realm.body = {**_DOCUMENT, "end_session_endpoint": _LOGOUT}
    settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID = _ISSUER, "bundesarchiv"
    session = _Session(tokens)
    monkeypatch.setattr(keycloak, "refresh", session.refresh)
    monkeypatch.setattr(keycloak, "_revoke", session.revoke)
    return session


_FRESH = keycloak.Tokens(access="a2", refresh="r2", claims={}, id_token="id2")


def test_logout_revokes_the_fresh_token_and_hints_its_id_token(
    realm: _Realm, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _logout_realm(realm, settings, monkeypatch, _FRESH)
    url = keycloak.logout_url(
        refresh_token="r1", post_logout_redirect_uri="https://archiv.example/"
    )
    assert session.refreshed == ["r1"]
    assert session.revoked == ["r2"]
    assert url is not None
    assert parse_qs(urlsplit(url).query)["id_token_hint"] == ["id2"]


def test_logout_without_a_refresh_cookie_sends_no_hint(
    realm: _Realm, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _logout_realm(realm, settings, monkeypatch, _FRESH)
    url = keycloak.logout_url(
        refresh_token=None, post_logout_redirect_uri="https://archiv.example/"
    )
    assert session.refreshed == []
    assert session.revoked == []
    assert url is not None
    assert "id_token_hint" not in parse_qs(urlsplit(url).query)


def test_logout_with_a_dead_refresh_token_revokes_nothing(
    realm: _Realm, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _logout_realm(realm, settings, monkeypatch, None)
    url = keycloak.logout_url(
        refresh_token="r1", post_logout_redirect_uri="https://archiv.example/"
    )
    assert session.revoked == []
    assert url is not None
    assert "id_token_hint" not in parse_qs(urlsplit(url).query)
