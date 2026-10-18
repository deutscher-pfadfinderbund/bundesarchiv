"""The OIDC seam (ADR 0018): the ``Realm`` port, its ``Tokens``, and what a realm's claims mean.

``Realm`` is what the login surface asks a realm, with one failure answer, ``None``;
``viewers.realm()`` picks the adapter (``keycloak.KeycloakRealm``, or the dev realm settings name).

The claims→Viewer mapping is a PURE function over the already-checked access-token claims:
``Realm.verify_access`` (signature, issuer, audience, expiry) runs before it and hands it a plain
dict, so the one authorization decision a request makes is testable as a table with no server in
sight.

Least privilege is the tie-breaker: only the exact realm role grants ``Archivist``; every other
authenticated user — including one whose token carries claims in shapes we do not recognize — is a
``Member``. Unknown shapes never raise.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from bundesarchiv.domain.viewer import Archivist, Member, Viewer

#: The Keycloak realm role that makes a person an Archivist. An external contract: the realm's
#: roles client-scope must map it into the token (deploy runbook), and renaming it there revokes
#: archivist access here.
ARCHIVIST_REALM_ROLE = "Bundesarchiv"


@dataclass(frozen=True, slots=True)
class Tokens:
    """A token response the browser keeps (ADR 0018): the access and offline refresh tokens, the
    CHECKED claims of the access token, and the ID token, kept only as the logout hint."""

    access: str
    refresh: str
    claims: Mapping[str, object]
    id_token: str | None


class Realm(Protocol):
    """``None`` is every failure: unconfigured, unreachable, refused, or not valid. The callers turn
    it into the plain 404 or ``Public``, so a half-configured realm authenticates nobody."""

    def authorization_url(self, *, state: str, nonce: str, redirect_uri: str) -> str | None:
        """Where the browser logs in; the answer comes back to ``redirect_uri`` with ``state``."""

    def fetch_tokens(self, *, code: str, nonce: str, redirect_uri: str) -> Tokens | None:
        """The ``Tokens`` an authorization code stands for, bound to this browser's ``nonce``."""

    def verify_access(self, access_token: str) -> Mapping[str, object] | None:
        """The checked claims of a current access token issued to this app."""

    def refresh(self, refresh_token: str) -> Tokens | None:
        """New ``Tokens`` for a refresh token."""

    def logout_url(self, *, refresh_token: str | None, post_logout_redirect_uri: str) -> str | None:
        """Where a logout sends the browser, after ending what the server can end."""


def viewer_from_claims(claims: Mapping[str, object]) -> Viewer:
    """The ``Viewer`` of checked access-token claims; no claim shape raises or escalates."""
    if ARCHIVIST_REALM_ROLE in _strings(_as_mapping(claims.get("realm_access")).get("roles")):
        username = claims.get("preferred_username")
        if isinstance(username, str) and username.strip():
            return Archivist(username=username)
        return Archivist()
    return Member(groups=_strings(claims.get("groups")))


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    """The non-empty strings in a JSON array claim; ``()`` for anything that is not an array. A bare
    string is NOT a one-element list here — ``in`` over a string is a substring test, which would
    read a role named ``xBundesarchivy`` as the archivist role."""
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
