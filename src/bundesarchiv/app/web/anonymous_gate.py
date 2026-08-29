"""The anonymous gate: an unauthenticated request is sent to the login, not answered (ADR 0018).

ONE check for the whole surface, as middleware — never a per-view decorator anybody could forget to
copy onto the next route. It runs on every path, method and status alike, so an anonymous visitor
cannot tell a real article from a made-up one: both are the same redirect.

``ANONYMOUS_GATE_ENABLED`` is TRUE in the base settings and false only in ``settings_dev`` — the
fail-closed direction. A production deploy that forgets its OIDC env vars still cannot fall open to
anonymous browsing; it redirects to a login that itself falls closed.
"""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from bundesarchiv.app.web.auth_views import login_redirect
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.viewer import Public

#: The routes the gate may never bounce: the login flow itself (bouncing it would be a loop) and the
#: logout, which must stay usable while the cookie it clears is unreadable.
_EXEMPT_ROUTES = ("login", "oidc-callback", "logout")


class AnonymousGateMiddleware:
    """Redirect every anonymous request to ``/login?next=<where they were going>``."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if _passes(request):
            return self.get_response(request)
        return _to_login(request)


def _to_login(request: HttpRequest) -> HttpResponse:
    """The bounce — as a HEADER for an htmx request. An XHR cannot follow the redirect: it ends at
    Keycloak's cross-origin authorize URL, where the browser blocks the response and htmx swaps
    nothing, so an expired cookie would turn every save and every search into a control that
    silently does nothing. ``HX-Redirect`` navigates the whole page, which is what a login needs."""
    target = login_redirect(request.get_full_path())
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response.headers["HX-Redirect"] = target
        return response
    return HttpResponseRedirect(target)


def _passes(request: HttpRequest) -> bool:
    return (
        not settings.ANONYMOUS_GATE_ENABLED
        or _is_exempt(request)
        or not isinstance(viewer_of(request), Public)
    )


def _is_exempt(request: HttpRequest) -> bool:
    """The paths that answer an anonymous request themselves. ``/static/*`` is public by design
    (ADR 0016) and WhiteNoise answers it before this middleware even runs — naming it here keeps that
    contract a decision rather than a consequence of the middleware order."""
    return request.path.startswith(settings.STATIC_URL) or request.path in {
        reverse(name) for name in _EXEMPT_ROUTES
    }
