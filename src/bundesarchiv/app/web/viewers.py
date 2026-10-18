"""``viewer_of(request) -> Viewer`` — THE request→Viewer trust boundary (Part 4.4).

ONE function the whole web layer calls to answer *who is asking* (domain ``Viewer``: Archivist |
Member(groups) | Public), through ONE path: a login's token cookies (ADR 0018), the access token
checked by ``realm()`` on every request and refreshed server-side through
``TokenCookieMiddleware`` when it has expired. Dev and the tests log in through the dev realm the
same way (ADR 0025).

Fail-closed everywhere: no cookie, an unconfigured realm, or a token the realm rejects ALL resolve
to ``Public()``. A bad cookie is never an error — only ever an anonymous viewer.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.utils.module_loading import import_string

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import landing, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.keycloak import KeycloakRealm
from bundesarchiv.app.web.oidc import Realm, Tokens, viewer_from_claims
from bundesarchiv.app.web.panels import FormPanel, header_panels
from bundesarchiv.domain.viewer import Archivist, Public, Viewer


@dataclass(frozen=True, slots=True)
class LoginCookies:
    """The names of the three cookies a login leaves (the access and refresh tokens, and the
    in-flight login's state) and whether they are Secure."""

    access: str
    refresh: str
    state: str
    secure: bool


def login_cookies() -> LoginCookies:
    """Where the site serves https (``CSRF_COOKIE_SECURE``), ``__Host-`` names and Secure: Keycloak
    lives on a sibling host of the same registrable domain, and without the prefix any such host
    could set a ``Domain=``-scoped cookie of these names that shadows ours, an unclearable login
    loop. Over dev's plain http, project names without Secure: WebKit drops a Secure cookie set
    over http, and cookies are not separated by port, so a bare name would clash with another
    localhost app's (ADR 0025)."""
    secure = settings.CSRF_COOKIE_SECURE
    prefix = "__Host-" if secure else "bundesarchiv_"
    return LoginCookies(prefix + "access", prefix + "refresh", prefix + "oidc_state", secure)


#: How long the browser keeps the token cookies. The realm's offline session idle (30 days) is the real limit;
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


def realm() -> Realm:
    """The login realm: ``settings.BUNDESARCHIV_REALM`` when set (dev and tests; the WSGI entry
    refuses to serve with it), else Keycloak. A settings module names it by dotted path, since
    settings may not import ``app``; a test passes the instance."""
    configured: Realm | str | None = getattr(settings, "BUNDESARCHIV_REALM", None)
    if isinstance(configured, str):
        realm_class: type[Realm] = import_string(configured)
        return realm_class()
    return configured if configured is not None else KeycloakRealm()


def set_token_cookies(tokens: Tokens, response: HttpResponse) -> None:
    """Set both token cookies on ``response`` (ADR 0018)."""
    if len(tokens.access) > _COOKIE_WARN_LENGTH:
        _log.warning("access token cookie is %d characters long", len(tokens.access))
    cookies = login_cookies()
    for name, value in ((cookies.access, tokens.access), (cookies.refresh, tokens.refresh)):
        response.set_cookie(
            name,
            value,
            max_age=_TOKEN_COOKIE_MAX_AGE,
            httponly=True,
            secure=cookies.secure,
            samesite="Lax",
        )


def delete_token_cookies(response: HttpResponse) -> None:
    cookies = login_cookies()
    for name in (cookies.access, cookies.refresh):
        response.delete_cookie(name, samesite="Lax")


def _token_viewer(request: HttpRequest) -> Viewer | None:
    """The viewer of an OIDC login's token cookies, or ``None`` when they do not resolve to one. A
    rejected or missing access token is refreshed with the refresh cookie; the outcome waits on the
    request for ``TokenCookieMiddleware``."""
    login, cookies = realm(), login_cookies()
    access = request.COOKIES.get(cookies.access)
    claims = login.verify_access(access) if access else None
    if claims is not None:
        return viewer_from_claims(claims)
    refresh_token = request.COOKIES.get(cookies.refresh)
    if not refresh_token:
        return None
    tokens = login.refresh(refresh_token)
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
        if not hasattr(request, _REFRESHED_ATTR) or login_cookies().access in response.cookies:
            return response
        tokens: Tokens | None = getattr(request, _REFRESHED_ATTR)
        if tokens is None:
            delete_token_cookies(response)
        else:
            set_token_cookies(tokens, response)
        return response


def viewer_of(request: HttpRequest) -> Viewer:
    """Never raises. Cached on the request so every reader agrees and the token is refreshed at
    most once."""
    cached: Viewer | None = getattr(request, _VIEWER_CACHE_ATTR, None)
    if cached is not None:
        return cached
    viewer = _token_viewer(request) or Public()
    setattr(request, _VIEWER_CACHE_ATTR, viewer)
    return viewer


def render_screen(
    request: HttpRequest,
    template: str,
    context: dict[str, object],
    *,
    chooser: CollectionChooser | None = None,
) -> HttpResponse:
    """The viewer-derived chrome is stamped over ``context``, so no caller can grant chrome the
    viewer has not earned."""
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
    if is_partial(request):
        return htmx_redirect(location)
    return HttpResponseRedirect(location)


def panel_response(request: HttpRequest, panel: FormPanel) -> HttpResponse:
    """``panel`` alone, as its tool panel swaps in place."""
    return render(request, "workbench/_formpanel.html", {"panel": panel})
