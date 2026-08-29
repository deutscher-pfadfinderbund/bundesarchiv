"""The discovery cache in the Keycloak adapter (ADR 0018): only a SUCCESS may be remembered.

The realm itself is deliberately not suite-tested (ADR 0018, "Testing") — a fake can only encode our
own assumptions about Keycloak. The CACHE is ours, and its failure mode is not a refused login but a
dead worker: a remembered ``None`` would answer every later login in that process, and with the
anonymous gate on, every request then loops through a login that 404s.
"""

from collections.abc import Iterator, Mapping

import httpx
import pytest

from bundesarchiv.app.web import keycloak

_ISSUER = "https://auth.example/realms/dpb"
_DOCUMENT: Mapping[str, object] = {
    "authorization_endpoint": f"{_ISSUER}/protocol/openid-connect/auth",
    "token_endpoint": f"{_ISSUER}/protocol/openid-connect/token",
}


class _Realm:
    """The discovery endpoint as an ``httpx.get`` stand-in — the ONE genuine external boundary here.
    ``down`` raises the connection failure a restarting realm gives; ``body`` is what it serves."""

    def __init__(self) -> None:
        self.down = False
        self.body: object = dict(_DOCUMENT)

    def get(self, url: str, **_: object) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("realm restarting")
        return httpx.Response(200, json=self.body, request=httpx.Request("GET", url))


@pytest.fixture
def realm(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Realm]:
    """A realm behind the adapter, with the process-wide cache empty before and after."""
    keycloak._DOCUMENTS.clear()
    fake = _Realm()
    # On the httpx module itself: the adapter calls ``httpx.get``, so this is the same attribute.
    monkeypatch.setattr(httpx, "get", fake.get)
    yield fake
    keycloak._DOCUMENTS.clear()


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
