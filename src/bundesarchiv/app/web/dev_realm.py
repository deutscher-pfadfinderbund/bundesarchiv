"""``DevRealm`` — the login realm dev and the tests log in through, behind the ``Realm`` port.

It signs its own codes and tokens with ``DEV_VIEWER_SIGNING_KEY`` through an explicit key, never
``SECRET_KEY``; production settings define no such key, so there it mints and verifies nothing.
The tokens carry Keycloak-shaped claims, so ``viewer_from_claims`` reads them as it reads
Keycloak's.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing

from bundesarchiv.app.web.oidc import ARCHIVIST_REALM_ROLE, Tokens
from bundesarchiv.domain.viewer import Archivist, Member

#: The page that stands in for Keycloak's login form.
AUTHORIZE_PATH = "/_dev/viewer/"

_CODE_SALT = "dev-realm-code"
_ACCESS_SALT = "dev-realm-access"
_REFRESH_SALT = "dev-realm-refresh"

#: Keycloak's offline session idle limit: each refresh issues a new refresh token.
_REFRESH_LIFETIME = 30 * 24 * 60 * 60


def claims_of(viewer: Archivist | Member) -> dict[str, object]:
    """The claims a login as ``viewer`` carries, shaped as Keycloak's, so ``viewer_from_claims``
    reads them back as ``viewer``."""
    match viewer:
        case Archivist(username=username):
            return {
                "realm_access": {"roles": [ARCHIVIST_REALM_ROLE]},
                "preferred_username": username,
            }
        case Member(groups=groups):
            return {"groups": list(groups)}


def _key() -> str | None:
    return getattr(settings, "DEV_VIEWER_SIGNING_KEY", None) or None


def _signed(payload: Mapping[str, object], salt: str) -> str | None:
    key = _key()
    return signing.dumps(dict(payload), key=key, salt=salt) if key else None


def _current(raw: str | None, salt: str) -> dict[str, Any] | None:
    """The payload of ``raw`` when this key signed it under ``salt`` and its ``exp`` lies ahead;
    ``None`` otherwise, a payload without ``exp`` included."""
    key = _key()
    if not key or not raw:
        return None
    try:
        payload: dict[str, Any] = signing.loads(raw, key=key, salt=salt)
    except signing.BadSignature:
        return None
    if payload.get("exp", 0) <= time.time():
        return None
    return payload


@dataclass(frozen=True, slots=True)
class DevRealm:
    """A ``Realm`` with no server. ``lifetime`` is how many seconds a code or an access token stays
    good, ``refresh_lifetime`` a refresh token (negative mints expired ones)."""

    lifetime: int = 60
    refresh_lifetime: int = _REFRESH_LIFETIME

    def _exp(self, lifetime: int | None = None) -> int:
        return int(time.time()) + (self.lifetime if lifetime is None else lifetime)

    def mint_code(self, claims: Mapping[str, object], *, nonce: str) -> str | None:
        """The authorization code a login as ``claims`` answers with, bound to ``nonce``."""
        return _signed({"claims": dict(claims), "nonce": nonce, "exp": self._exp()}, _CODE_SALT)

    def mint_tokens(self, claims: Mapping[str, object]) -> Tokens | None:
        """``Tokens`` for ``claims``: a fresh access token and a refresh token that re-issues it."""
        access_claims = {**claims, "exp": self._exp()}
        access = _signed(access_claims, _ACCESS_SALT)
        refresh = _signed({**claims, "exp": self._exp(self.refresh_lifetime)}, _REFRESH_SALT)
        if access is None or refresh is None:
            return None
        return Tokens(access=access, refresh=refresh, claims=access_claims, id_token=None)

    def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str | None:
        if _key() is None:
            return None
        query = urlencode({"state": state, "nonce": nonce, "redirect_uri": redirect_uri})
        return f"{AUTHORIZE_PATH}?{query}"

    def fetch_tokens(
        self,
        *,
        code: str,
        nonce: str,
        redirect_uri: str,  # noqa: ARG002
    ) -> Tokens | None:
        payload = _current(code, _CODE_SALT)
        if payload is None or payload["nonce"] != nonce:
            return None
        return self.mint_tokens(payload["claims"])

    def verify_access(self, access_token: str) -> Mapping[str, object] | None:
        return _current(access_token, _ACCESS_SALT)

    def refresh(self, refresh_token: str) -> Tokens | None:
        claims = _current(refresh_token, _REFRESH_SALT)
        return self.mint_tokens(claims) if claims is not None else None

    def logout_url(
        self,
        *,
        refresh_token: str | None,  # noqa: ARG002
        post_logout_redirect_uri: str,
    ) -> str | None:
        return post_logout_redirect_uri if _key() is not None else None
