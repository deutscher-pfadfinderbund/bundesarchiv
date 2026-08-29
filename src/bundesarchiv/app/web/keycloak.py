"""The Keycloak provider adapter — the ONE place that talks to the realm (ADR 0018).

Three functions, one failure answer: ``None`` for an unconfigured setting, an unreachable realm, a
refused code or an ID token that does not validate. The views turn that into the plain 404 every
other deny on this surface is, so a half-configured deploy authenticates nobody instead of trusting
something it cannot verify.

These lines are NOT suite-tested, deliberately (ADR 0018 "Testing"): the realistic failure here is
Keycloak CLIENT misconfiguration — a missing roles mapper, a redirect URI that does not match — and
a fake of this seam can only encode our own assumptions about the realm. One real login per realm
change is the deploy runbook's smoke step. What IS tested is everything above the seam (the views
run against an in-memory fake of these three names) and the discovery cache below, whose failure
mode is not a refused login but a worker that can never log anybody in again.
"""

from collections.abc import Mapping
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from django.conf import settings

#: What the authorize request asks for: ``openid`` for the ID token itself; the realm's roles
#: client-scope maps ``realm_access.roles`` into it (runbook), which is what makes an Archivist.
_SCOPE = "openid profile"

#: Seconds any single Keycloak call may take. A login is interactive — a hanging realm must become a
#: deny quickly rather than tie up a worker.
_TIMEOUT = 10.0


#: Discovery documents already fetched, keyed by issuer so a settings change (tests, a re-pointed
#: deploy) cannot be served another realm's document. SUCCESSES ONLY — see ``_metadata``.
_DOCUMENTS: dict[str, Mapping[str, object]] = {}


def _metadata(issuer: str) -> Mapping[str, object] | None:
    """The realm's OIDC discovery document, fetched once per issuer per process and kept for the
    life of it. A FAILURE is never remembered: memoizing the ``None`` would let one restarting realm
    disable login in that worker until somebody restarts it."""
    cached = _DOCUMENTS.get(issuer)
    if cached is not None:
        return cached
    try:
        response = httpx.get(
            f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=_TIMEOUT
        )
        response.raise_for_status()
        document = response.json()
    except httpx.HTTPError, ValueError:
        return None
    if not isinstance(document, Mapping):
        return None
    _DOCUMENTS[issuer] = document
    return document


def _endpoint(name: str) -> str | None:
    """One endpoint URL from the discovery document, or ``None`` when the realm is unconfigured,
    unreachable, or does not advertise it."""
    issuer = settings.OIDC_ISSUER
    document = _metadata(issuer) if issuer else None
    endpoint = document.get(name) if document else None
    return endpoint if isinstance(endpoint, str) and endpoint else None


def authorization_url(*, state: str, nonce: str, redirect_uri: str) -> str | None:
    """The URL that starts the authorization-code flow for THIS browser, carrying its ``state`` and
    ``nonce`` (both ride back in the app's transient cookie for comparison)."""
    endpoint = _endpoint("authorization_endpoint")
    if endpoint is None or not settings.OIDC_CLIENT_ID:
        return None
    client = OAuth2Client(
        client_id=settings.OIDC_CLIENT_ID, scope=_SCOPE, redirect_uri=redirect_uri
    )
    try:
        url, _state = client.create_authorization_url(endpoint, state=state, nonce=nonce)
    finally:
        client.close()
    return str(url)


def fetch_claims(*, code: str, nonce: str, redirect_uri: str) -> Mapping[str, object] | None:
    """Exchange an authorization code for the ID token and return its VALIDATED claims — signature
    against the realm's JWKS, issuer, audience, expiry, and the ``nonce`` this browser's authorize
    request carried. ``None`` for any failure; the caller denies."""
    # Imported here, not at module scope: authlib's `jose` package emits a deprecation warning on
    # import (it is supported until authlib 2.0), and a real login is the only code path that needs
    # it — startup and the whole test suite stay clear of both the warning and the import cost.
    from authlib.common.errors import AuthlibBaseError
    from authlib.jose import JsonWebKey, jwt
    from authlib.oidc.core import CodeIDToken

    issuer, client_id, client_secret = (
        settings.OIDC_ISSUER,
        settings.OIDC_CLIENT_ID,
        settings.OIDC_CLIENT_SECRET,
    )
    token_endpoint, jwks_uri = _endpoint("token_endpoint"), _endpoint("jwks_uri")
    if not (issuer and client_id and client_secret and token_endpoint and jwks_uri):
        return None
    client = OAuth2Client(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )
    try:
        token = client.fetch_token(
            token_endpoint, code=code, grant_type="authorization_code", timeout=_TIMEOUT
        )
        jwks = httpx.get(jwks_uri, timeout=_TIMEOUT).raise_for_status().json()
        claims = jwt.decode(
            token["id_token"],
            JsonWebKey.import_key_set(jwks),
            claims_cls=CodeIDToken,
            claims_options={
                "iss": {"essential": True, "value": issuer},
                "aud": {"essential": True, "value": client_id},
            },
            claims_params={"nonce": nonce},
        )
        claims.validate()
    except AuthlibBaseError, httpx.HTTPError, KeyError, ValueError:
        return None
    finally:
        client.close()
    return dict(claims)


def end_session_url(*, post_logout_redirect_uri: str) -> str | None:
    """Where a logout sends the browser so the SSO session dies with the local cookie, or ``None``
    when the realm is unconfigured/unreachable (the caller then still clears its own cookie).

    Carries no ``id_token_hint`` — the app stores no tokens (ADR 0018) — so Keycloak asks the user
    to CONFIRM the logout rather than ending the session outright. The local cookie is already gone
    at that point; the SSO session survives an unconfirmed logout. That residual is the runbook's
    smoke step 4 and ADR 0018's open point, not an oversight here."""
    endpoint = _endpoint("end_session_endpoint")
    if endpoint is None or not settings.OIDC_CLIENT_ID:
        return None
    query = urlencode(
        {
            "client_id": settings.OIDC_CLIENT_ID,
            "post_logout_redirect_uri": post_logout_redirect_uri,
        }
    )
    return f"{endpoint}?{query}"
