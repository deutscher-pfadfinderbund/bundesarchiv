"""``viewer_of(request) -> Viewer`` — THE request→Viewer trust boundary (Part 4.4).

ONE function the whole web layer calls to answer *who is asking* (domain ``Viewer``: Archivist |
Member(groups) | Public). TWO adapters answer it; the UI code above never knows which one spoke:

- an OIDC login's token cookies (ADR 0018): Keycloak's access token, checked on every request and
  refreshed server-side through ``TokenCookieMiddleware`` when it has expired;
- the cookie the dev-only switcher sets (``dev`` module), keyed by ``DEV_VIEWER_SIGNING_KEY``,
  which only ``settings_dev`` defines — never the production ``SECRET_KEY``, so a leaked dev
  cookie is worthless against a deployment.

Fail-closed everywhere: no cookie, no key configured, a tampered/expired signature, or a payload
that does not parse to a known viewer shape ALL resolve to ``Public()``. A bad cookie is never an
error — only ever an anonymous viewer.
"""

import logging
from collections.abc import Callable
from enum import StrEnum
from urllib.parse import quote, unquote

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.utils.cache import patch_vary_headers

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import landing, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.keycloak import Tokens, refresh, verify_access
from bundesarchiv.app.web.oidc import viewer_from_claims
from bundesarchiv.app.web.panels import FormPanel, header_panels
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: Name of the signed cookie the dev switcher sets and this seam reads.
DEV_VIEWER_COOKIE = "dev_viewer"

_DEV_VIEWER_SALT = "dev-viewer"

#: A working day; an expired dev cookie is Public.
_DEV_VIEWER_MAX_AGE = 12 * 60 * 60

#: The two cookies an OIDC login leaves the browser holding (ADR 0018): Keycloak's access token and
#: its offline refresh token. The ``__Host-`` prefix is a browser-enforced lock, and this deployment
#: needs it: Keycloak lives on a sibling host of the same registrable domain, and any such host could
#: otherwise set a ``Domain=``-scoped cookie of this name that shadows ours — an unclearable login
#: loop. The dev cookie above carries no prefix on purpose: ``__Host-`` requires Secure, which dev's
#: plain http cannot satisfy.
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
    """The inverse of ``encode_viewer``; ``None`` for any other shape, including a bare
    ``archivist``."""
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
    """The request's ``Viewer``: token cookies first, then the dev switcher, else ``Public()``; never
    raises. Cached on the request so every reader agrees and the token is refreshed at most once."""
    cached: Viewer | None = getattr(request, _VIEWER_CACHE_ATTR, None)
    if cached is not None:
        return cached
    viewer = _token_viewer(request) or _switched_viewer(request) or Public()
    setattr(request, _VIEWER_CACHE_ATTR, viewer)
    return viewer


def render_screen(
    request: HttpRequest,
    template: str,
    context: dict[str, object],
    *,
    chooser: CollectionChooser | None = None,
) -> HttpResponse:
    """Render ``template`` with the viewer-derived chrome stamped over ``context`` — ``is_archivist``,
    ``is_signed_in``, ``index_lag`` and the archivist's ``new`` panels — so no caller can grant chrome
    the viewer has not earned."""
    viewer = viewer_of(request)
    is_archivist = isinstance(viewer, Archivist)
    chrome: dict[str, object] = {
        "is_archivist": is_archivist,
        "is_signed_in": not isinstance(viewer, Public),
        "new": (),
        "index_lag": vocab.INDEX_LAG if is_archivist and landing.index_lagging(request) else "",
    }
    if is_archivist:
        active = context.get("active_collection")
        # a callable: the template calls it where the header prints the menu, so a partial pays nothing
        chrome["new"] = lambda: header_panels(
            chooser or CollectionChooser.of(Archive.canonical()),
            active=active if isinstance(active, str) else None,
        )
    return render(request, template, {**context, **chrome})


_HX_RESTORE = "HX-History-Restore-Request"
_HX_REQUEST = "HX-Request"


class RequestKind(StrEnum):
    """What the browser asked for — the closed answer ``request_kind`` gives."""

    PAGE = "page"  # a plain request: the whole document
    PARTIAL = "partial"  # an htmx swap: the region only
    RESTORE = "restore"  # an htmx history restore (Back button): swaps the whole body


def request_kind(request: HttpRequest) -> RequestKind:
    """THE reader of the ``HX-`` request headers (``tests/test_structure.py`` gates it).

    A restore is checked first: htmx 4 sends ``HX-History-Restore-Request`` without ``HX-Request``
    and htmx 2 sent both, so a restore can never be mistaken for a swap that takes the
    chrome-less partial."""
    if request.headers.get(_HX_RESTORE):
        return RequestKind.RESTORE
    if request.headers.get(_HX_REQUEST):
        return RequestKind.PARTIAL
    return RequestKind.PAGE


def vary_on_request_kind(
    get_response: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """Name the headers ``request_kind`` reads in ``Vary`` on every response. One URL answers a
    fragment or a whole page by those headers, and the workbench pushes it as a page URL: without
    this the browser cache serves the fragment on Back. Sits above ``AnonymousGateMiddleware`` so
    the door is covered too."""

    def middleware(request: HttpRequest) -> HttpResponse:
        response = get_response(request)
        patch_vary_headers(response, (_HX_REQUEST, _HX_RESTORE))
        return response

    return middleware


def is_partial(request: HttpRequest) -> bool:
    """Did htmx ask for a region swap (not a page, not a history restore)?"""
    return request_kind(request) is RequestKind.PARTIAL


def htmx_redirect(location: str) -> HttpResponse:
    """A 204 carrying ``HX-Redirect``: htmx does a full browser navigation to ``location``."""
    response = HttpResponse(status=204)
    response["HX-Redirect"] = location
    return response


def redirect_to(request: HttpRequest, location: str) -> HttpResponseBase:
    """A 302 to ``location``, or for an htmx swap the ``HX-Redirect`` equivalent."""
    if is_partial(request):
        return htmx_redirect(location)
    return HttpResponseRedirect(location)


def panel_response(request: HttpRequest, panel: FormPanel) -> HttpResponse:
    """``panel`` alone, as its tool panel swaps in place."""
    return render(request, "workbench/_formpanel.html", {"panel": panel})
