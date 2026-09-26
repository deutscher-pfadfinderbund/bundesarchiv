"""The access-token check (ADR 0018): the one decision every request makes about a Keycloak token.

Tokens are signed here with generated RSA keys. The realm's HTTP endpoints are an ``httpx2.get``
stand-in, as in ``test_keycloak_discovery``; the check itself runs for real.
"""

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64encode
from collections.abc import Iterator, Mapping
from functools import partial
from typing import Any

import httpx2
import pytest
from authlib.integrations.httpx_client import OAuth2Client
from authlib.jose import JsonWebKey, JsonWebToken
from pytest_django.fixtures import Settings

from bundesarchiv.app.web import keycloak

_ISSUER = "https://auth.example/realms/dpb"
_CLIENT = "bundesarchiv"
_JWKS_URI = f"{_ISSUER}/protocol/openid-connect/certs"

_OLD = JsonWebKey.generate_key("RSA", 2048, is_private=True)
_NEW = JsonWebKey.generate_key("RSA", 2048, is_private=True)
_KIDS = {id(_OLD): "old", id(_NEW): "new"}


def _public_set(*keys: Any) -> Mapping[str, object]:
    return {"keys": [{**k.as_dict(is_private=False), "kid": _KIDS[id(k)]} for k in keys]}


def _claims(**overrides: object) -> dict[str, object]:
    now = int(time.time())
    base: dict[str, object] = {
        "iss": _ISSUER,
        "aud": _CLIENT,
        "typ": "Bearer",
        "exp": now + 60,
        "iat": now,
        "preferred_username": "anna",
        "realm_access": {"roles": ["Bundesarchiv"]},
    }
    return base | overrides


def _without(name: str) -> dict[str, object]:
    return {k: v for k, v in _claims().items() if k != name}


def _token(claims: Mapping[str, object] | None = None, *, key: Any = _OLD) -> str:
    header = {"alg": "RS256", "kid": _KIDS[id(key)]}
    encoded: bytes = JsonWebToken(["RS256"]).encode(header, dict(claims or _claims()), key)
    return encoded.decode()


def _segment(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode()


def _json_segment(value: Mapping[str, object]) -> str:
    return _segment(json.dumps(value).encode())


class _Realm:
    """Discovery document and key set behind ``httpx2.get``; counts key-set fetches."""

    def __init__(self) -> None:
        self.keys: Mapping[str, object] = _public_set(_OLD)
        self.key_fetches = 0

    def get(self, url: str, **_: object) -> httpx2.Response:
        if url == _JWKS_URI:
            self.key_fetches += 1
            body: object = self.keys
        else:
            body = {
                "jwks_uri": _JWKS_URI,
                "token_endpoint": f"{_ISSUER}/protocol/openid-connect/token",
            }
        return httpx2.Response(200, json=body, request=httpx2.Request("GET", url))


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Iterator[_Realm]:
    settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID = _ISSUER, _CLIENT
    keycloak._DOCUMENTS.clear()
    keycloak._KEY_SETS.clear()
    fake = _Realm()
    monkeypatch.setattr(httpx2, "get", fake.get)
    yield fake
    keycloak._DOCUMENTS.clear()
    keycloak._KEY_SETS.clear()


def test_a_valid_token_yields_its_claims(realm: _Realm) -> None:
    claims = keycloak.verify_access(_token())
    assert claims is not None
    assert claims["preferred_username"] == "anna"


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param(_claims(exp=int(time.time()) - 1), id="expired"),
        pytest.param(_claims(iss="https://auth.example/realms/other"), id="other-issuer"),
        pytest.param(_claims(aud="another-dpb-app"), id="other-client"),
        pytest.param(_without("aud"), id="no-audience"),
        pytest.param(_claims(typ="ID"), id="an-id-token"),
        pytest.param(_without("exp"), id="no-expiry"),
    ],
)
def test_a_token_that_is_not_ours_or_not_current_is_rejected(
    realm: _Realm, claims: Mapping[str, object]
) -> None:
    assert keycloak.verify_access(_token(claims)) is None


def test_a_tampered_token_is_rejected(realm: _Realm) -> None:
    header, _, signature = _token().split(".")
    _, forged, _ = _token(_claims(realm_access={"roles": ["Bundesarchiv", "x"]})).split(".")
    assert keycloak.verify_access(f"{header}.{forged}.{signature}") is None


def test_an_unsigned_token_is_rejected(realm: _Realm) -> None:
    token = f"{_json_segment({'alg': 'none', 'kid': 'old'})}.{_json_segment(_claims())}."
    assert keycloak.verify_access(token) is None


def test_a_token_hmac_signed_with_the_public_key_is_rejected(realm: _Realm) -> None:
    """The classic algorithm confusion: HS256 keyed with the realm's public key."""
    head = _json_segment({"alg": "HS256", "kid": "old"})
    body = _json_segment(_claims())
    secret = _OLD.as_pem(is_private=False)
    signature = hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
    assert keycloak.verify_access(f"{head}.{body}.{_segment(signature)}") is None


def test_a_rotated_key_costs_one_refetch(realm: _Realm) -> None:
    assert keycloak.verify_access(_token()) is not None
    realm.keys = _public_set(_OLD, _NEW)
    assert keycloak.verify_access(_token(key=_NEW)) is not None
    assert realm.key_fetches == 2


def test_an_expired_token_with_a_known_key_does_not_refetch(realm: _Realm) -> None:
    """Every access token expires within minutes; its expiry may not cost a key-set fetch."""
    assert keycloak.verify_access(_token()) is not None
    assert keycloak.verify_access(_token(_claims(exp=int(time.time()) - 1))) is None
    assert realm.key_fetches == 1


@pytest.mark.parametrize(
    "garbage",
    [
        pytest.param("", id="empty"),
        pytest.param("abc", id="no-dots"),
        pytest.param("a.b.c", id="junk-segments"),
        pytest.param("ü.ü.ü", id="non-ascii"),
        pytest.param("x" * 10_000, id="10k"),
        pytest.param("e30.e30.", id="empty-objects"),
        pytest.param("...", id="only-dots"),
    ],
)
def test_garbage_is_rejected_without_a_refetch(realm: _Realm, garbage: str) -> None:
    assert keycloak.verify_access(_token()) is not None  # warm the cache
    assert keycloak.verify_access(garbage) is None
    assert realm.key_fetches == 1


def test_an_unconfigured_realm_accepts_nothing(realm: _Realm, settings: Settings) -> None:
    settings.OIDC_CLIENT_ID = None
    assert keycloak.verify_access(_token()) is None


@pytest.mark.parametrize(
    "body",
    [
        pytest.param([], id="list"),
        pytest.param("x", id="string"),
        pytest.param(5, id="number"),
        pytest.param(None, id="null"),
    ],
)
def test_a_refresh_answer_that_is_not_an_object_is_a_failed_refresh(
    realm: _Realm, settings: Settings, monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    """A proxy or a misbehaving realm answering 200 with a non-object: ``viewer_of`` must still fall
    closed rather than raise (a 500 on every request, the cookies never cleared)."""
    settings.OIDC_CLIENT_SECRET = "secret"
    # The realm behind the client's transport: no network, and no SSL context either (building one
    # starts a native thread on macOS, which the suite's fork-based tests then warn about).
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(200, json=body))
    monkeypatch.setattr(keycloak, "OAuth2Client", partial(OAuth2Client, transport=transport))
    assert keycloak.refresh("r1") is None
