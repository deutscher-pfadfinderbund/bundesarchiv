"""``viewer_of(request) -> Viewer`` — THE request→Viewer trust boundary (Part 4.4).

ONE function the whole web layer calls to answer *who is asking* (domain ``Viewer``: Archivist |
Member(groups) | Public). THREE adapters answer it; the UI code above never knows which one spoke:

- an OIDC login's token cookies (ADR 0018): Keycloak's access token, checked on every request and
  refreshed server-side through ``TokenCookieMiddleware`` when it has expired;
- a minted Viewer cookie (``mint_viewer_cookie``, the capability-link seam), keyed by
  ``VIEWER_SIGNING_KEY``;
- the cookie the dev-only switcher sets (``dev`` module), keyed by ``DEV_VIEWER_SIGNING_KEY``,
  which only ``settings_dev`` defines.

Neither key is ever the production ``SECRET_KEY``: a leaked dev cookie is worthless against a
deployment, and each seam falls closed wherever its key is absent.

Fail-closed everywhere: no cookie, no key configured, a tampered/expired signature, a superseded
format version, or a payload that does not parse to a known viewer shape ALL resolve to
``Public()``. A bad cookie is never an error — only ever an anonymous viewer.
"""

import logging
from collections.abc import Callable
from urllib.parse import quote, unquote

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bundesarchiv.app.web.keycloak import Tokens, refresh, verify_access
from bundesarchiv.app.web.oidc import viewer_from_claims
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: Name of the signed cookie the dev switcher sets and this seam reads.
DEV_VIEWER_COOKIE = "dev_viewer"

#: Signer salt namespacing the dev-viewer cookie (kept separate from any other signed value).
_DEV_VIEWER_SALT = "dev-viewer"

#: How long a dev-viewer cookie stays valid (12h — a working day; expired ones fall back to Public).
_DEV_VIEWER_MAX_AGE = 12 * 60 * 60

#: Name of the signed cookie a production OIDC login mints and this seam reads. The ``__Host-``
#: prefix is a browser-enforced lock, and this deployment needs it: Keycloak lives on a sibling host
#: of the same registrable domain, and any such host could otherwise set a ``Domain=``-scoped cookie
#: of this name that shadows ours — an unclearable login loop. The dev cookie above carries no
#: prefix on purpose: ``__Host-`` requires Secure, which dev's plain http cannot satisfy.
VIEWER_COOKIE = "__Host-viewer"

#: The two cookies an OIDC login leaves the browser holding (ADR 0018): Keycloak's access token and
#: its offline refresh token. ``__Host-`` for the reason ``VIEWER_COOKIE`` gives.
ACCESS_COOKIE = "__Host-access"
REFRESH_COOKIE = "__Host-refresh"

#: How long the browser keeps them. The realm's offline session idle (30 days) is the real limit;
#: each refresh sets them again.
_TOKEN_COOKIE_MAX_AGE = 30 * 24 * 60 * 60

#: Above this a browser may drop a cookie silently; the viewer would then refresh on every request.
_COOKIE_WARN_LENGTH = 4000

#: Where ``viewer_of`` parks a refresh outcome — new ``Tokens``, or ``None`` to drop both cookies —
#: for ``TokenCookieMiddleware``. Namespaced like ``_VIEWER_CACHE_ATTR``.
_REFRESHED_ATTR = "_bundesarchiv_refreshed"

_log = logging.getLogger(__name__)

#: Signer salt for the production cookie — its own namespace, never the dev cookie's.
_VIEWER_SALT = "viewer"

#: Format version carried in the cookie payload. Bumping it invalidates every outstanding minted
#: Viewer cookie at once — the capability-link seam's emergency lever; OIDC logins are revoked in
#: Keycloak (ADR 0018). ``v3``: the OIDC callback stopped minting this cookie.
_VIEWER_FORMAT_VERSION = "v3"

#: Per-tier lifetimes of a MINTED Viewer cookie (the capability-link seam); OIDC logins follow the
#: realm's offline session instead (ADR 0018). Enforced on read, not only offered to the browser.
#: The member window is also the OUTER bound — no viewer cookie verifies beyond it.
_ARCHIVIST_MAX_AGE = 48 * 60 * 60
_MEMBER_MAX_AGE = 30 * 24 * 60 * 60

#: Where ``viewer_of`` parks the request's resolved Viewer. Namespaced: ``HttpRequest`` is Django's
#: and any attribute on it is shared with middleware nobody here controls.
_VIEWER_CACHE_ATTR = "_bundesarchiv_viewer"


def _dev_signer() -> signing.TimestampSigner | None:
    """The dev-viewer signer, keyed by ``settings.DEV_VIEWER_SIGNING_KEY`` — or ``None`` when that
    setting is absent (i.e. under production settings, which never define it). Passing ``key``
    explicitly is load-bearing: it structurally prevents Django from falling back to
    ``SECRET_KEY``, so the dev cookie is signed/verified ONLY with the dedicated dev key."""
    key = getattr(settings, "DEV_VIEWER_SIGNING_KEY", None)
    if not key:
        return None
    return signing.TimestampSigner(key=key, salt=_DEV_VIEWER_SALT)


def _viewer_signer() -> signing.TimestampSigner | None:
    """The production viewer signer, keyed by ``settings.VIEWER_SIGNING_KEY`` — or ``None`` when the
    deploy supplied no key. Passing ``key`` explicitly keeps Django from falling back to
    ``SECRET_KEY``, so this cookie is signed and verified ONLY with its dedicated key."""
    key = settings.VIEWER_SIGNING_KEY
    if not key:
        return None
    return signing.TimestampSigner(key=key, salt=_VIEWER_SALT)


def _max_age(viewer: Viewer) -> int:
    return _ARCHIVIST_MAX_AGE if isinstance(viewer, Archivist) else _MEMBER_MAX_AGE


def mint_viewer_cookie(viewer: Viewer, response: HttpResponse) -> bool:
    """Set the signed production Viewer cookie for ``viewer`` on ``response``, for the tier's own
    lifetime. Returns ``False`` having set NOTHING when no ``VIEWER_SIGNING_KEY`` is configured —
    the caller must then deny rather than hand out an identity nobody can verify."""
    signer = _viewer_signer()
    if signer is None:
        return False
    payload = signer.sign(f"{_VIEWER_FORMAT_VERSION}:{encode_viewer(viewer)}")
    response.set_cookie(
        VIEWER_COOKIE,
        payload,
        max_age=_max_age(viewer),
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return True


def encode_viewer(viewer: Viewer) -> str:
    """Serialize a ``Viewer`` to the cookie's plaintext payload (the value the signer then wraps):
    ``archivist:<username>`` | ``member:group1,group2`` | ``public``. Every name is percent-escaped,
    so it may carry the delimiters; a Member with no groups encodes as a bare ``member``."""
    match viewer:
        case Archivist(username=username):
            return "archivist:" + quote(username, safe="")
        case Member(groups=groups):
            return "member:" + ",".join(quote(g, safe="") for g in groups) if groups else "member"
        case Public():
            return "public"


def _parse_viewer(payload: str) -> Viewer | None:
    """Parse a verified cookie payload back to a ``Viewer``, or ``None`` if it is not a known shape.
    STRICT: only the exact vocabulary ``archivist:<username>`` / ``public`` / ``member`` /
    ``member:<groups>`` is accepted; anything else (a signed-but-garbage payload, or a bare
    ``archivist`` with no name) yields ``None`` so the caller floors to Public. Names are
    percent-unescaped (the inverse of ``encode_viewer``). Empty group entries are dropped so
    ``member:a,,b`` -> groups ``(a, b)``."""
    if payload.startswith("archivist:"):
        return Archivist(username=unquote(payload.removeprefix("archivist:")))
    if payload == "public":
        return Public()
    if payload == "member":
        return Member(groups=())
    if payload.startswith("member:"):
        groups = tuple(unquote(g) for g in payload.removeprefix("member:").split(",") if g)
        return Member(groups=groups)
    return None


def _unsign(signer: signing.TimestampSigner, raw: str | None, max_age: int) -> str | None:
    """The verified payload of ``raw``, or ``None`` for anything the signer rejects — absent,
    tampered or expired (``SignatureExpired`` is a ``BadSignature``)."""
    if not raw:
        return None
    try:
        return signer.unsign(raw, max_age=max_age)
    except signing.BadSignature:
        return None


def _minted_viewer(request: HttpRequest) -> Viewer | None:
    """The viewer of the production cookie, or ``None`` when there is no verified one to read."""
    signer = _viewer_signer()
    if signer is None:
        return None
    raw = request.COOKIES.get(VIEWER_COOKIE)
    version, _, encoded = (_unsign(signer, raw, _MEMBER_MAX_AGE) or "").partition(":")
    if version != _VIEWER_FORMAT_VERSION:
        return None
    viewer = _parse_viewer(encoded)
    if viewer is None:
        return None
    # The window above is only the outer bound; each tier's cookie dies on its own.
    return viewer if _unsign(signer, raw, _max_age(viewer)) is not None else None


def _switched_viewer(request: HttpRequest) -> Viewer | None:
    """The viewer of the dev switcher's cookie, or ``None`` — including under production settings,
    which define no dev key at all."""
    signer = _dev_signer()
    if signer is None:
        return None
    payload = _unsign(signer, request.COOKIES.get(DEV_VIEWER_COOKIE), _DEV_VIEWER_MAX_AGE)
    return _parse_viewer(payload) if payload is not None else None


def set_token_cookies(tokens: Tokens, response: HttpResponse) -> None:
    """Set both token cookies on ``response`` (ADR 0018)."""
    if len(tokens.access) > _COOKIE_WARN_LENGTH:
        _log.warning("access token cookie is %d characters long", len(tokens.access))
    for name, value in ((ACCESS_COOKIE, tokens.access), (REFRESH_COOKIE, tokens.refresh)):
        response.set_cookie(
            name,
            value,
            max_age=_TOKEN_COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="Lax",
        )


def delete_token_cookies(response: HttpResponse) -> None:
    """Delete both token cookies on ``response``."""
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, samesite="Lax")


def _token_viewer(request: HttpRequest) -> Viewer | None:
    """The viewer of an OIDC login's token cookies, or ``None`` when they do not resolve to one. A
    rejected or missing access token is refreshed with the refresh cookie; the outcome waits on the
    request for ``TokenCookieMiddleware``."""
    access = request.COOKIES.get(ACCESS_COOKIE)
    claims = verify_access(access) if access else None
    if claims is not None:
        return viewer_from_claims(claims)
    refresh_token = request.COOKIES.get(REFRESH_COOKIE)
    if not refresh_token:
        return None
    tokens = refresh(refresh_token)
    setattr(request, _REFRESHED_ATTR, tokens)
    return viewer_from_claims(tokens.claims) if tokens is not None else None


class TokenCookieMiddleware:
    """Write a refresh outcome onto the response: the new token cookies, or their deletion when the
    refresh failed. ``viewer_of`` runs before any response exists, so it cannot. A view that set or
    deleted the token cookies itself (the callback, logout) decides alone."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not hasattr(request, _REFRESHED_ATTR) or ACCESS_COOKIE in response.cookies:
            return response
        tokens: Tokens | None = getattr(request, _REFRESHED_ATTR)
        if tokens is None:
            delete_token_cookies(response)
        else:
            set_token_cookies(tokens, response)
        return response


def viewer_of(request: HttpRequest) -> Viewer:
    """Resolve the request's ``Viewer`` — the single web-layer trust boundary. An OIDC login's token
    cookies answer first, then a minted Viewer cookie, then the dev switcher, which only ever
    answers where a dev key is configured. Every failure mode of every adapter falls closed to
    ``Public()``; a bad cookie never raises.

    Resolved once per request and cached on the request: the four call sites (gate, view, article
    authorization, ``render_screen``) then cannot answer *who is asking* differently, and the
    token is checked — and at most refreshed — once instead of once each. Sound because cookie state
    cannot change mid-request — mint and clear happen on the response."""
    cached: Viewer | None = getattr(request, _VIEWER_CACHE_ATTR, None)
    if cached is not None:
        return cached
    viewer = (
        _token_viewer(request) or _minted_viewer(request) or _switched_viewer(request) or Public()
    )
    setattr(request, _VIEWER_CACHE_ATTR, viewer)
    return viewer


def render_screen(request: HttpRequest, template: str, context: dict[str, object]) -> HttpResponse:
    """Render a screen with ``is_archivist`` and ``is_signed_in`` resolved HERE, from ``viewer_of``.

    The shared header's "+ Neu …" create disclosure is ARCHIVIST CHROME, so whether it renders is an
    authorization-shaped fact — and an authorization fact is the view's to decide, exactly as
    ``browse_views`` decides it for the workbench and the detail reader. Four include sites used to
    ASSERT it (``{% include "workbench/_header.html" with is_archivist=True %}``) on the grounds that
    their routes are archivist-gated. True today, and unfalsifiable by the leak matrix, which asserts
    route gates and never chrome: the day a screen with this header is reached by a lower tier — a
    member-facing Lesesaal composition, a capability-link surface — the template would hand out
    archivist chrome without a word. One helper, and the fact comes from the viewer everywhere.

    ``is_signed_in`` is the shared header's OTHER gate, and a different question: Abmelden belongs to
    whoever holds a cookie, not to archivists (a Member's cookie is the longer-lived of the two, and
    the shared workstation is the normal case — ADR 0018).

    This helper is the SINGLE authority for both keys: they are stamped over ``context``, so no
    caller can assert chrome the viewer has not earned."""
    viewer = viewer_of(request)
    return render(
        request,
        template,
        {
            **context,
            "is_archivist": isinstance(viewer, Archivist),
            "is_signed_in": not isinstance(viewer, Public),
        },
    )
