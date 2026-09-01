"""What the Keycloak adapter decides for itself (ADR 0018): its caches and the URLs it builds.

The realm itself is deliberately not suite-tested (ADR 0018, "Testing") — a fake can only encode our
own assumptions about Keycloak. The CACHE is ours, and its failure mode is not a refused login but a
dead worker: a remembered ``None`` would answer every later login in that process, and with the
anonymous gate on, every request then loops through a login that 404s.
"""

from collections.abc import Iterator, Mapping
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pytest_django.fixtures import Settings

from bundesarchiv.app.web import keycloak

_ISSUER = "https://auth.example/realms/dpb"
_LOGOUT = f"{_ISSUER}/protocol/openid-connect/logout"
_JWKS_URI = f"{_ISSUER}/protocol/openid-connect/certs"
_DOCUMENT: Mapping[str, object] = {
    "authorization_endpoint": f"{_ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{_ISSUER}/protocol/openid-connect/token",
}
_KEY_SET: Mapping[str, object] = {"keys": [{"kid": "signing-2026-08", "kty": "RSA"}]}
_ROTATED: Mapping[str, object] = {"keys": [{"kid": "signing-2026-09", "kty": "RSA"}]}


class _Realm:
    """The realm's HTTP endpoints as an ``httpx.get`` stand-in — the ONE genuine external boundary
    here. ``down`` raises the connection failure a restarting realm gives; ``body`` is what it
    serves."""

    def __init__(self) -> None:
        self.down = False
        self.body: object = dict(_DOCUMENT)

    def get(self, url: str, **_: object) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("realm restarting")
        return httpx.Response(200, json=self.body, request=httpx.Request("GET", url))


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Realm]:
    """A realm behind the adapter, with the process-wide caches empty before and after."""
    keycloak._DOCUMENTS.clear()
    keycloak._KEY_SETS.clear()
    fake = _Realm()
    # On the httpx module itself: the adapter calls ``httpx.get``, so this is the same attribute.
    monkeypatch.setattr(httpx, "get", fake.get)
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
    assert keycloak._jwks(_JWKS_URI) == _KEY_SET


def test_a_fetched_key_set_outlives_the_realm(realm: _Realm) -> None:
    """Why the cache exists: a callback validates the ID token without a second round trip to the
    realm, serially after the token exchange it already paid for."""
    realm.body = dict(_KEY_SET)
    assert keycloak._jwks(_JWKS_URI) == _KEY_SET
    realm.down = True
    assert keycloak._jwks(_JWKS_URI) == _KEY_SET


def test_a_refresh_replaces_the_cached_key_set_only_when_it_succeeds(realm: _Realm) -> None:
    """What makes a signing-key rotation survivable — and what keeps an outage during one from
    throwing away the set that still verifies yesterday's keys."""
    realm.body = dict(_KEY_SET)
    assert keycloak._jwks(_JWKS_URI) == _KEY_SET

    realm.body = dict(_ROTATED)
    assert keycloak._jwks(_JWKS_URI, refresh=True) == _ROTATED
    realm.down = True
    assert keycloak._jwks(_JWKS_URI) == _ROTATED
    assert keycloak._jwks(_JWKS_URI, refresh=True) is None
    assert keycloak._jwks(_JWKS_URI) == _ROTATED


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

    url = keycloak.end_session_url(post_logout_redirect_uri="https://archiv.example/")

    assert url is not None
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == _LOGOUT
    assert parse_qs(parts.query) == {
        **realms_own,
        "client_id": ["bundesarchiv"],
        "post_logout_redirect_uri": ["https://archiv.example/"],
    }
