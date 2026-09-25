"""OIDC login adapter — validated Keycloak claims → domain ``Viewer`` (ADR 0018).

The claims→Viewer mapping is a PURE function over the already-validated ID-token claims: the
authlib flow (issuer/nonce/signature validation) happens before it and hands it a plain dict, so
the one authorization decision a login makes is testable as a table with no server in sight.

Least privilege is the tie-breaker: only the exact realm role grants ``Archivist``; every other
authenticated user — including one whose token carries claims in shapes we do not recognize — is a
``Member``. Unknown shapes never raise.
"""

from collections.abc import Mapping

from bundesarchiv.domain.viewer import Archivist, Member, Viewer

#: The Keycloak realm role that makes a person an Archivist. An external contract: the realm's
#: roles client-scope must map it into the token (deploy runbook), and renaming it there revokes
#: archivist access here.
ARCHIVIST_REALM_ROLE = "Bundesarchiv"


def viewer_from_claims(claims: Mapping[str, object]) -> Viewer:
    """Map validated ID-token claims to the ``Viewer`` a login mints a cookie for: ``Archivist``
    for the realm role ``Bundesarchiv`` in ``realm_access.roles``, named by ``preferred_username``
    (the default name when that is absent or blank), otherwise ``Member`` carrying the ``groups``
    claim (empty when absent — group rollout is then Keycloak configuration, not code). Claims of
    an unexpected type are read as absent, so no token shape can raise or escalate."""
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
