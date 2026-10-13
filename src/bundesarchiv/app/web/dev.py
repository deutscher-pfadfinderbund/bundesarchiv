"""Dev-only viewer switcher, signed under the dev-only key and mounted only by ``dev_urls``."""

from html import escape

from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseRedirect,
)
from django.middleware.csrf import get_token
from django.urls import reverse

from bundesarchiv.app.web.viewers import (
    _DEV_VIEWER_MAX_AGE,
    DEV_VIEWER_COOKIE,
    _dev_signer,
    encode_viewer,
    viewer_of,
)
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


def favicon(request: HttpRequest) -> HttpResponse:
    return HttpResponseNotFound()


def _viewer_from_post(request: HttpRequest) -> Viewer:
    """Build the chosen ``Viewer`` from the switcher form POST. Unknown/absent kind -> ``Public()``
    (fail-closed even in the dev switcher)."""
    kind = request.POST.get("kind", "")
    if kind == "archivist":
        username = request.POST.get("username", "").strip()
        return Archivist(username=username) if username else Archivist()
    if kind == "member":
        raw = request.POST.get("groups", "")
        groups = tuple(g for g in raw.replace(",", " ").split() if g)
        return Member(groups=groups)
    return Public()


def switch_viewer(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        signer = _dev_signer()
        # only settings_dev mounts this, and it defines the key
        if signer is None:
            return HttpResponseRedirect(reverse("dev-switch-viewer"))
        signed = signer.sign(encode_viewer(_viewer_from_post(request)))
        response = HttpResponseRedirect(reverse("dev-switch-viewer"))
        response.set_cookie(
            DEV_VIEWER_COOKIE, signed, max_age=_DEV_VIEWER_MAX_AGE, httponly=True, samesite="Lax"
        )
        return response
    return HttpResponse(_render_form(viewer_of(request), csrf_token=get_token(request)))


def _describe(viewer: Viewer) -> str:
    """Human-readable German label for the currently active viewer (shown at the top of the form)."""
    match viewer:
        case Archivist(username=username):
            return f"Archivar {username} (sieht alles)"
        case Member(groups=groups):
            return "Mitglied — Gruppen: " + (", ".join(groups) if groups else "(keine)")
        case Public():
            return "Öffentlich (nicht angemeldet)"


def _render_form(current: Viewer, *, csrf_token: str) -> str:
    return (
        "<!doctype html><html lang=de><head><meta charset=utf-8>"
        '<link rel="stylesheet" href="/static/tokens.css">'
        '<link rel="stylesheet" href="/static/components.css">'
        '<link rel="stylesheet" href="/static/layouts.css">'
        "<title>Dev: Betrachter wechseln</title></head><body>"
        '<main class="stub">'
        "<h1>Betrachter wechseln (nur Entwicklung)</h1>"
        f"<p>Aktuell: <strong>{escape(_describe(current))}</strong></p>"
        f'<form method=post action="{reverse("dev-switch-viewer")}">'
        f'<input type=hidden name=csrfmiddlewaretoken value="{escape(csrf_token)}">'
        "<p><label><input type=radio name=kind value=archivist> Archivar</label>"
        " Benutzername: <input type=text name=username></p>"
        "<p><label><input type=radio name=kind value=member checked> Mitglied</label>"
        ' Gruppen: <input type=text name=groups placeholder="gruppe1, gruppe2"></p>'
        "<p><label><input type=radio name=kind value=public> Öffentlich</label></p>"
        '<p><button class="primary" type=submit>Übernehmen</button></p>'
        "</form></main></body></html>"
    )
