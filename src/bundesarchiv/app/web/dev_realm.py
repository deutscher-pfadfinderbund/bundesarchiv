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

from bundesarchiv.app.web.oidc import Tokens

#: The page that stands in for Keycloak's login form.
AUTHORIZE_PATH = "/_dev/viewer/"

_CODE_SALT = "dev-realm-code"
_ACCESS_SALT = "dev-realm-access"
_REFRESH_SALT = "dev-realm-refresh"

#: One call to the realm: the operation's name and its arguments.
type Asked = list[tuple[str, dict[str, str | None]]]


def _key() -> str | None:
    return getattr(settings, "DEV_VIEWER_SIGNING_KEY", None) or None


def _signed(payload: Mapping[str, object], salt: str) -> str | None:
    key = _key()
    return signing.dumps(dict(payload), key=key, salt=salt) if key else None


def _current(raw: str | None, salt: str) -> dict[str, Any] | None:
    """The payload of ``raw`` when this key signed it under ``salt`` and its ``exp`` (if it carries
    one) lies ahead; ``None`` otherwise."""
    key = _key()
    if not key or not raw:
        return None
    try:
        payload: dict[str, Any] = signing.loads(raw, key=key, salt=salt)
    except signing.BadSignature:
        return None
    if "exp" in payload and payload["exp"] <= time.time():
        return None
    return payload


@dataclass(frozen=True, slots=True)
class DevRealm:
    """A ``Realm`` with no server. ``lifetime`` is how many seconds a code or an access token stays
    good (negative mints expired ones); ``asked``, when given, records every call."""

    lifetime: int = 60
    asked: Asked | None = None

    def _ask(self, operation: str, **args: str | None) -> None:
        if self.asked is not None:
            self.asked.append((operation, args))

    def _exp(self) -> int:
        return int(time.time()) + self.lifetime

    def mint_code(self, claims: Mapping[str, object], *, nonce: str) -> str | None:
        """The authorization code a login as ``claims`` answers with, bound to ``nonce``."""
        return _signed({"claims": dict(claims), "nonce": nonce, "exp": self._exp()}, _CODE_SALT)

    def mint_tokens(self, claims: Mapping[str, object]) -> Tokens | None:
        """``Tokens`` for ``claims``: a fresh access token and a refresh token that re-issues it."""
        access_claims = {**claims, "exp": self._exp()}
        access = _signed(access_claims, _ACCESS_SALT)
        refresh = _signed(claims, _REFRESH_SALT)
        if access is None or refresh is None:
            return None
        return Tokens(access=access, refresh=refresh, claims=access_claims, id_token=None)

    def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str | None:
        self._ask("authorization_url", state=state, nonce=nonce, redirect_uri=redirect_uri)
        if _key() is None:
            return None
        query = urlencode({"state": state, "nonce": nonce, "redirect_uri": redirect_uri})
        return f"{AUTHORIZE_PATH}?{query}"

    def fetch_tokens(self, *, code: str, nonce: str, redirect_uri: str) -> Tokens | None:
        self._ask("fetch_tokens", code=code, nonce=nonce, redirect_uri=redirect_uri)
        payload = _current(code, _CODE_SALT)
        if payload is None or payload["nonce"] != nonce:
            return None
        return self.mint_tokens(payload["claims"])

    def verify_access(self, access_token: str) -> Mapping[str, object] | None:
        self._ask("verify_access", access_token=access_token)
        return _current(access_token, _ACCESS_SALT)

    def refresh(self, refresh_token: str) -> Tokens | None:
        self._ask("refresh", refresh_token=refresh_token)
        claims = _current(refresh_token, _REFRESH_SALT)
        return self.mint_tokens(claims) if claims is not None else None

    def logout_url(self, *, refresh_token: str | None, post_logout_redirect_uri: str) -> str | None:
        self._ask(
            "logout_url",
            refresh_token=refresh_token,
            post_logout_redirect_uri=post_logout_redirect_uri,
        )
        return post_logout_redirect_uri if _key() is not None else None
