"""The Keycloak provider adapter — the ONE place that talks to the realm (ADR 0018).

``authorization_url``, ``fetch_tokens``, ``verify_access``, ``refresh`` and ``logout_url``, one
failure answer: ``None`` for an unconfigured setting, an unreachable realm, a refused code or
refresh token, or a token that does not validate. The callers turn that into the plain 404 or
``Public``, so a half-configured deploy authenticates nobody instead of trusting something it cannot
verify.

The authlib calls are NOT suite-tested, deliberately (ADR 0018 "Testing"): the realistic failure
here is Keycloak CLIENT misconfiguration — a missing mapper, a redirect URI that does not match — and
a fake of this seam can only encode our own assumptions about the realm. One real login per realm
change is the deploy runbook's smoke step. What IS tested is everything above the seam (the views
run against an in-memory fake of these names), the token check, the logout step order, the URLs
built here, and the caches below, whose failure mode is not a refused login but a worker that can
never log anybody in again.
"""

import json
from base64 import urlsafe_b64decode
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx2
from authlib.common.errors import AuthlibBaseError
from authlib.common.urls import add_params_to_uri
from authlib.integrations.httpx_client import OAuth2Client
from django.conf import settings

#: What the authorize request asks for: ``openid`` for the ID token; ``profile`` for
#: ``preferred_username``, which names an Archivist; ``offline_access`` for the 30-day offline
#: refresh token (ADR 0018). Roles and groups reach the access token through the client's mappers
#: (runbook).
_SCOPE = "openid profile offline_access"

#: Seconds any single Keycloak call may take. A login is interactive — a hanging realm must become a
#: deny quickly rather than tie up a worker.
_TIMEOUT = 10.0

#: The one signing algorithm a token may use (ADR 0018). The realm also advertises HMAC algorithms;
#: accepting one would let a token be forged with the realm's PUBLIC key as the HMAC secret.
_ALGORITHMS = ["RS256"]


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
        response = httpx2.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        document = response.json()
    except httpx2.HTTPError, ValueError:
        return None
    if not isinstance(document, Mapping):
        return None
    cache[url] = document
    return document


def _metadata(issuer: str) -> Mapping[str, object] | None:
    """The realm's OIDC discovery document."""
    return _fetched(f"{issuer.rstrip('/')}/.well-known/openid-configuration", _DOCUMENTS)


def _jwks(jwks_uri: str, *, refresh: bool = False) -> Mapping[str, object] | None:
    """The realm's signing keys. Cached because every request's token check needs them; a key
    ROTATION is the one thing that invalidates them, which the token checks recognise from a token
    they cannot verify and answer with ``refresh``."""
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


def _decoded(
    token: str,
    jwks: Mapping[str, object],
    *,
    options: Mapping[str, object],
    claims_cls: type | None = None,
    params: Mapping[str, object] | None = None,
) -> Mapping[str, object] | None:
    """``token``'s claims, verified against ``jwks`` with ``_ALGORITHMS`` only and validated against
    ``options``; ``None`` for anything that does not hold."""
    # Imported here, not at module scope: authlib's `jose` package emits a deprecation warning on
    # import (it is supported until authlib 2.0); startup and most of the suite stay clear of it.
    from authlib.jose import JsonWebKey, JsonWebToken

    try:
        claims = JsonWebToken(_ALGORITHMS).decode(
            token,
            JsonWebKey.import_key_set(dict(jwks)),
            claims_cls=claims_cls,
            claims_options=dict(options),
            claims_params=dict(params) if params else None,
        )
        claims.validate()
    except AuthlibBaseError, KeyError, ValueError:
        return None
    return dict(claims)


def _validated(
    id_token: str, jwks: Mapping[str, object], *, issuer: str, client_id: str, nonce: str
) -> Mapping[str, object] | None:
    """The ID token's claims checked against ``jwks`` — signature, issuer, audience, expiry and the
    ``nonce`` this browser's authorize request carried — or ``None``."""
    from authlib.oidc.core import CodeIDToken

    return _decoded(
        id_token,
        jwks,
        options={
            "iss": {"essential": True, "value": issuer},
            "aud": {"essential": True, "value": client_id},
        },
        claims_cls=CodeIDToken,
        params={"nonce": nonce},
    )


def _kid(token: str) -> str | None:
    """The ``kid`` of a JWT's UNVERIFIED header — read only to decide whether the cached key set can
    know the signing key at all."""
    segment = token.split(".", 1)[0]
    try:
        header = json.loads(urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except ValueError:
        return None
    kid = header.get("kid") if isinstance(header, dict) else None
    return kid if isinstance(kid, str) else None


def _kids(jwks: Mapping[str, object]) -> set[object]:
    keys = jwks.get("keys")
    return (
        {k.get("kid") for k in keys if isinstance(k, Mapping)} if isinstance(keys, list) else set()
    )


def verify_access(access_token: str) -> Mapping[str, object] | None:
    """The claims of a Keycloak access token issued to THIS client, or ``None`` when any check fails:
    signature against the realm's keys (``RS256`` only), ``iss``, ``aud`` naming this client, ``typ``
    ``Bearer``, and ``exp`` (ADR 0018). The realm signs other apps' tokens with the same keys; the
    audience is what makes a token ours."""
    issuer, client_id = settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID
    jwks_uri = _endpoint("jwks_uri")
    if not (issuer and client_id and jwks_uri):
        return None
    jwks = _jwks(jwks_uri)
    kid = _kid(access_token)
    if jwks is not None and kid is not None and kid not in _kids(jwks):
        # A rotated realm key. ponytail: a forged token naming an unknown kid also costs one key-set
        # fetch per request; add a refetch cooldown if that ever shows up in the realm's load.
        jwks = _jwks(jwks_uri, refresh=True)
    if jwks is None:
        return None
    return _decoded(
        access_token,
        jwks,
        options={
            "iss": {"essential": True, "value": issuer},
            "aud": {"essential": True, "value": client_id},
            "exp": {"essential": True},
            "typ": {"essential": True, "value": "Bearer"},
        },
    )


@dataclass(frozen=True, slots=True)
class Tokens:
    """A token response the browser keeps (ADR 0018): the access and offline refresh tokens, the
    CHECKED claims of the access token, and the ID token, kept only as the logout hint."""

    access: str
    refresh: str
    claims: Mapping[str, object]
    id_token: str | None


def _client(redirect_uri: str | None = None) -> OAuth2Client | None:
    """The confidential client, or ``None`` while its id or secret is unconfigured."""
    client_id, client_secret = settings.OIDC_CLIENT_ID, settings.OIDC_CLIENT_SECRET
    if not (client_id and client_secret):
        return None
    return OAuth2Client(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


#: What a token-endpoint call raises when the realm refuses, cannot be reached, or answers nonsense:
#: a 200 whose body is not a JSON object makes authlib raise ``TypeError`` before any caller sees it.
_REALM_ERRORS = (AuthlibBaseError, httpx2.HTTPError, ValueError, TypeError)


def _call(
    client: OAuth2Client, request: Callable[[OAuth2Client], object]
) -> Mapping[str, object] | None:
    """Run one call against the realm and close the client: the JSON object it answered, or
    ``None`` for any failure."""
    try:
        response = request(client)
    except _REALM_ERRORS:
        return None
    finally:
        client.close()
    return response if isinstance(response, Mapping) else None


def _tokens_of(response: Mapping[str, object]) -> Tokens | None:
    """The ``Tokens`` in a token-endpoint response, or ``None`` unless it carries both tokens and the
    access token passes ``verify_access``."""
    access, refresh_token = response.get("access_token"), response.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh_token, str):
        return None
    claims = verify_access(access)
    if claims is None:
        return None
    id_token = response.get("id_token")
    return Tokens(
        access=access,
        refresh=refresh_token,
        claims=claims,
        id_token=id_token if isinstance(id_token, str) else None,
    )


def fetch_tokens(*, code: str, nonce: str, redirect_uri: str) -> Tokens | None:
    """Exchange an authorization code for ``Tokens``. The ID token must match this browser's
    ``nonce``; the access token must pass ``verify_access``. ``None`` for any failure."""
    issuer, client_id = settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID
    token_endpoint, jwks_uri = _endpoint("token_endpoint"), _endpoint("jwks_uri")
    if not (issuer and client_id and token_endpoint and jwks_uri):
        return None
    client = _client(redirect_uri)
    if client is None:
        return None
    response = _call(
        client,
        lambda c: c.fetch_token(
            token_endpoint, code=code, grant_type="authorization_code", timeout=_TIMEOUT
        ),
    )
    if response is None:
        return None
    id_token = response.get("id_token")
    jwks = _jwks(jwks_uri) if isinstance(id_token, str) else None
    if not isinstance(id_token, str) or jwks is None:
        return None
    if _validated(id_token, jwks, issuer=issuer, client_id=client_id, nonce=nonce) is None:
        # A rotated realm key is simply absent from the cached set; one refetch tells it apart.
        rotated = _jwks(jwks_uri, refresh=True)
        if (
            rotated is None
            or _validated(id_token, rotated, issuer=issuer, client_id=client_id, nonce=nonce)
            is None
        ):
            return None
    return _tokens_of(response)


def refresh(refresh_token: str) -> Tokens | None:
    """New ``Tokens`` for a refresh token, or ``None`` when the realm refuses it or cannot be
    reached — the caller then treats the viewer as signed out (ADR 0018)."""
    token_endpoint = _endpoint("token_endpoint")
    client = _client() if token_endpoint else None
    if client is None:
        return None
    response = _call(
        client,
        lambda c: c.refresh_token(token_endpoint, refresh_token=refresh_token, timeout=_TIMEOUT),
    )
    return _tokens_of(response) if response is not None else None


def _revoke(refresh_token: str) -> None:
    """Revoke an offline refresh token at the realm. Best effort: a logout goes on without it."""
    endpoint = _endpoint("revocation_endpoint")
    client = _client() if endpoint else None
    if client is not None:
        _call(
            client,
            lambda c: c.revoke_token(
                endpoint,
                token=refresh_token,
                token_type_hint="refresh_token",  # noqa: S106 — an OAuth parameter name, not a secret
                timeout=_TIMEOUT,
            ),
        )


def _end_session_url(post_logout_redirect_uri: str, *, id_token_hint: str | None) -> str | None:
    """Keycloak's end-session URL, joined onto whatever query the realm advertises, or ``None`` when
    the realm is unconfigured or unreachable."""
    endpoint = _endpoint("end_session_endpoint")
    if endpoint is None or not settings.OIDC_CLIENT_ID:
        return None
    params = [
        ("client_id", settings.OIDC_CLIENT_ID),
        ("post_logout_redirect_uri", post_logout_redirect_uri),
    ]
    if id_token_hint:
        params.append(("id_token_hint", id_token_hint))
    return str(add_params_to_uri(endpoint, params))


def logout_url(*, refresh_token: str | None, post_logout_redirect_uri: str) -> str | None:
    """Where a logout sends the browser, after ending what the server can end (ADR 0018 "Logout"):
    refresh once for a current ID token, revoke the offline token, then the end-session URL with
    that ``id_token_hint``, so Keycloak ends its own session without asking. The step order lives
    here and nowhere else. ``None`` when the realm is unconfigured or unreachable; the caller clears
    its cookies either way."""
    tokens = refresh(refresh_token) if refresh_token else None
    if tokens is not None:
        _revoke(tokens.refresh)
    hint = tokens.id_token if tokens is not None else None
    return _end_session_url(post_logout_redirect_uri, id_token_hint=hint)
