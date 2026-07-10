"""Dev-only viewer switcher — middleware + switcher view (Part 4.4).

This module is referenced ONLY from ``settings_dev`` (its ``MIDDLEWARE`` and ``dev_urls``). Under
production settings it is never added to ``MIDDLEWARE`` and its route never appears in the URLconf,
so the switcher is UNREACHABLE in production by absence of code paths — not by a runtime flag that
could be flipped on. The cookie it sets is signed with the dedicated dev key (see ``viewers``),
worthless against any production deployment.

The middleware resolves ``viewer_of(request)`` once and attaches it to ``request.viewer`` for the
views below it. The switcher view (GET) shows a dead-simple German form to pick a viewer; (POST)
sets the signed cookie and redirects back to itself.
"""

from collections.abc import Callable
from html import escape

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from bundesarchiv.app.web.viewers import (
    _DEV_VIEWER_MAX_AGE,
    DEV_VIEWER_COOKIE,
    _dev_signer,
    encode_viewer,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: The switcher's own path (dev URLconf mounts it; nothing in prod references it).
SWITCHER_PATH = "/_dev/viewer/"


class DevViewerMiddleware:
    """Attach the request's ``Viewer`` (from the signed dev cookie) to ``request.viewer``.

    Dev-only: installed solely by ``settings_dev.MIDDLEWARE``. Views/templates read
    ``request.viewer``; Part 5 swaps the underlying ``viewer_of`` for the OIDC adapter and this
    middleware keeps working unchanged."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.viewer = viewer_of(request)  # type: ignore[attr-defined]
        return self.get_response(request)


def _viewer_from_post(request: HttpRequest) -> Viewer:
    """Build the chosen ``Viewer`` from the switcher form POST. Unknown/absent kind -> ``Public()``
    (fail-closed even in the dev switcher). Groups come from a comma/space-separated text field."""
    kind = request.POST.get("kind", "")
    if kind == "archivist":
        return Archivist()
    if kind == "member":
        raw = request.POST.get("groups", "")
        groups = tuple(g for g in raw.replace(",", " ").split() if g)
        return Member(groups=groups)
    return Public()


def switch_viewer(request: HttpRequest) -> HttpResponse:
    """Dev switcher: GET renders the picker (current viewer + form); POST signs the chosen viewer
    into the dev cookie and redirects back. Never mounted under production settings."""
    if request.method == "POST":
        signer = _dev_signer()
        if (
            signer is None
        ):  # defensive: this view only runs under settings_dev, which defines the key
            return HttpResponseRedirect(SWITCHER_PATH)
        signed = signer.sign(encode_viewer(_viewer_from_post(request)))
        response = HttpResponseRedirect(SWITCHER_PATH)
        response.set_cookie(
            DEV_VIEWER_COOKIE, signed, max_age=_DEV_VIEWER_MAX_AGE, httponly=True, samesite="Lax"
        )
        return response
    return HttpResponse(_render_form(viewer_of(request)))


def _describe(viewer: Viewer) -> str:
    """Human-readable German label for the currently active viewer (shown at the top of the form)."""
    match viewer:
        case Archivist():
            return "Archivar (sieht alles)"
        case Member(groups=groups):
            return "Mitglied — Gruppen: " + (", ".join(groups) if groups else "(keine)")
        case Public():
            return "Öffentlich (nicht angemeldet)"


def _render_form(current: Viewer) -> str:
    """Minimal no-JS German switcher form: three radio choices + a groups text input. Dev-only; it
    borrows the design-system stylesheet stack (same-origin, self-contained) for a consistent minimal
    look — no styling of its own beyond the shared ``wb-stub`` shell."""
    return (
        "<!doctype html><html lang=de><head><meta charset=utf-8>"
        '<link rel="stylesheet" href="/static/tokens.css">'
        '<link rel="stylesheet" href="/static/components.css">'
        '<link rel="stylesheet" href="/static/layouts.css">'
        "<title>Dev: Betrachter wechseln</title></head><body class=wb>"
        '<main class="wb-stub">'
        "<h1>Betrachter wechseln (nur Entwicklung)</h1>"
        f"<p>Aktuell: <strong>{escape(_describe(current))}</strong></p>"
        f'<form method=post action="{SWITCHER_PATH}">'
        "<p><label><input type=radio name=kind value=archivist> Archivar</label></p>"
        "<p><label><input type=radio name=kind value=member checked> Mitglied</label>"
        ' Gruppen: <input type=text name=groups placeholder="gruppe1, gruppe2"></p>'
        "<p><label><input type=radio name=kind value=public> Öffentlich</label></p>"
        '<p><button class="c-btn c-btn--primary" type=submit>Übernehmen</button></p>'
        "</form></main></body></html>"
    )
