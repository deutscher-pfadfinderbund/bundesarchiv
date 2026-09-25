"""The Keycloak provider adapter — the ONE place that talks to the realm (ADR 0018).

Three functions, one failure answer: ``None`` for an unconfigured setting, an unreachable realm, a
refused code or an ID token that does not validate. The views turn that into the plain 404 every
other deny on this surface is, so a half-configured deploy authenticates nobody instead of trusting
something it cannot verify.

These lines are NOT suite-tested, deliberately (ADR 0018 "Testing"): the realistic failure here is
Keycloak CLIENT misconfiguration — a missing roles mapper, a redirect URI that does not match — and
a fake of this seam can only encode our own assumptions about the realm. One real login per realm
change is the deploy runbook's smoke step. What IS tested is everything above the seam (the views
run against an in-memory fake of these three names), the URLs built here, and the caches below,
whose failure mode is not a refused login but a worker that can never log anybody in again.
"""

from collections.abc import Mapping

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.common.urls import add_params_to_uri
from authlib.integrations.httpx_client import OAuth2Client
from django.conf import settings

#: What the authorize request asks for: ``openid`` for the ID token itself; the realm's roles
#: client-scope maps ``realm_access.roles`` into it (runbook), which is what makes an Archivist;
#: ``profile`` maps ``preferred_username``, which names one.
_SCOPE = "openid profile"

#: Seconds any single Keycloak call may take. A login is interactive — a hanging realm must become a
#: deny quickly rather than tie up a worker.
_TIMEOUT = 10.0


#: What the realm has already told us, keyed by the URL it came from so a settings change (tests, a
#: re-pointed deploy) cannot be served another realm's answer. SUCCESSES ONLY — see ``_fetched``.
_DOCUMENTS: dict[str, Mapping[str, object]] = {}
_KEY_SETS: dict[str, Mapping[str, object]] = {}


def _fetched(
    url: str, cache: dict[str, Mapping[str, object]], *, refresh: bool = False
) -> Mapping[str, object] | None:
    """A JSON object from the realm, fetched once per process and kept for the life of it. A FAILURE
    is never remembered: memoizing the ``None`` would let one restarting realm disable login in that
    worker until somebody restarts it. ``refresh`` fetches past the cache and, on success only,
    replaces what it holds — a failed refresh keeps the answer that still works."""
    cached = None if refresh else cache.get(url)
    if cached is not None:
        return cached
    try:
        response = httpx.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        document = response.json()
    except httpx.HTTPError, ValueError:
        return None
    if not isinstance(document, Mapping):
        return None
    cache[url] = document
    return document


def _metadata(issuer: str) -> Mapping[str, object] | None:
    """The realm's OIDC discovery document."""
    return _fetched(f"{issuer.rstrip('/')}/.well-known/openid-configuration", _DOCUMENTS)


def _jwks(jwks_uri: str, *, refresh: bool = False) -> Mapping[str, object] | None:
    """The realm's signing keys. Cached because every callback needs them, serially after the token
    exchange it has already paid for; a key ROTATION is the one thing that invalidates them, which
    ``fetch_claims`` recognises from the token it cannot verify and answers with ``refresh``."""
    return _fetched(jwks_uri, _KEY_SETS, refresh=refresh)


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


def _validated(
    id_token: str, jwks: Mapping[str, object], *, issuer: str, client_id: str, nonce: str
) -> Mapping[str, object] | None:
    """The ID token's claims checked against ``jwks`` — signature, issuer, audience, expiry and the
    ``nonce`` this browser's authorize request carried — or ``None`` for a key set that cannot
    verify the token and for any claim that does not hold."""
    # Imported here, not at module scope: authlib's `jose` package emits a deprecation warning on
    # import (it is supported until authlib 2.0), and a real login is the only code path that needs
    # it — startup and the whole test suite stay clear of both the warning and the import cost.
    from authlib.jose import JsonWebKey, jwt
    from authlib.oidc.core import CodeIDToken

    try:
        claims = jwt.decode(
            id_token,
            JsonWebKey.import_key_set(dict(jwks)),
            claims_cls=CodeIDToken,
            claims_options={
                "iss": {"essential": True, "value": issuer},
                "aud": {"essential": True, "value": client_id},
            },
            claims_params={"nonce": nonce},
        )
        claims.validate()
    except AuthlibBaseError, KeyError, ValueError:
        return None
    return dict(claims)


def fetch_claims(*, code: str, nonce: str, redirect_uri: str) -> Mapping[str, object] | None:
    """Exchange an authorization code for the ID token and return its VALIDATED claims — signature
    against the realm's JWKS, issuer, audience, expiry, and the ``nonce`` this browser's authorize
    request carried. ``None`` for any failure; the caller denies."""
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
    except AuthlibBaseError, httpx.HTTPError, ValueError:
        return None
    finally:
        client.close()
    id_token = token.get("id_token")
    if not isinstance(id_token, str):
        return None
    jwks = _jwks(jwks_uri)
    if jwks is None:
        return None
    claims = _validated(id_token, jwks, issuer=issuer, client_id=client_id, nonce=nonce)
    if claims is not None:
        return claims
    # A rotated realm key is simply absent from the cached set, and that failure is indistinguishable
    # from a token that does not verify at all. One refetch tells the two apart.
    rotated = _jwks(jwks_uri, refresh=True)
    if rotated is None:
        return None
    return _validated(id_token, rotated, issuer=issuer, client_id=client_id, nonce=nonce)


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
    return str(
        add_params_to_uri(
            endpoint,
            [
                ("client_id", settings.OIDC_CLIENT_ID),
                ("post_logout_redirect_uri", post_logout_redirect_uri),
            ],
        )
    )
