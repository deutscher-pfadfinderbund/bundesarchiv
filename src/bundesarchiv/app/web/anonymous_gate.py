"""The anonymous gate: an unauthenticated request gets the door, not an answer (ADR 0018).

ONE check for the whole surface, as middleware — never a per-view decorator anybody could forget to
copy onto the next route. It runs on every path, method and status alike, so an anonymous visitor
cannot tell a real article from a made-up one: both are the same door.

``ANONYMOUS_GATE_ENABLED`` is TRUE in the base settings and false only in ``settings_dev`` — the
fail-closed direction. A production deploy that forgets its OIDC env vars still cannot fall open to
anonymous browsing; its door leads to a login that itself falls closed.
"""

from collections.abc import Callable
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from bundesarchiv.app.web.auth_views import login_redirect, safe_next
from bundesarchiv.app.web.viewers import RequestKind, htmx_redirect, request_kind, viewer_of
from bundesarchiv.domain.viewer import Public

#: The routes the gate may never bounce: the login flow itself (bouncing it would be a loop) and the
#: logout, which must stay usable while the cookie it clears is unreadable.
_EXEMPT_ROUTES = ("login", "oidc-callback", "logout")


class AnonymousGateMiddleware:
    """Answer every anonymous request with the door, whose login keeps where they were going."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if _passes(request):
            return self.get_response(request)
        return _door(request)


def _door(request: HttpRequest) -> HttpResponse:
    """The door — or, for an htmx request, the login as a HEADER. A swapped-in door would land
    inside whatever region the request targeted, and a 302 to the login ends at Keycloak's
    cross-origin authorize URL, where the browser blocks the response and htmx swaps nothing: an
    expired cookie would turn every save and every search into a control that silently does
    nothing. ``HX-Redirect`` navigates the whole page, which is what a login needs."""
    if request_kind(request) is not RequestKind.PAGE:
        return htmx_redirect(login_redirect(request.get_full_path()))
    anmelden = login_redirect(safe_next(request.get_full_path()) or "/")
    return render(request, "workbench/door.html", {"anmelden": anmelden})


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
    return request.path.startswith(settings.STATIC_URL) or request.path in _exempt_paths()


@lru_cache(maxsize=1)
def _exempt_paths() -> frozenset[str]:
    """Resolved on the first gated request, not at import: the URLconf is not loaded when this
    module is. The answer is a runtime constant, so one resolution serves the process."""
    return frozenset(reverse(name) for name in _EXEMPT_ROUTES)
