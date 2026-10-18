"""The dev realm's login page, mounted only by ``dev_urls``: where ``DevRealm.authorization_url``
sends the browser, as Keycloak's login form would (ADR 0025)."""

from html import escape
from urllib.parse import urlencode

from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseNotFound,
    HttpResponseRedirect,
    QueryDict,
)
from django.middleware.csrf import get_token
from django.urls import reverse

from bundesarchiv.app.web.auth_views import callback_uri, login_redirect
from bundesarchiv.app.web.dev_realm import DevRealm, claims_of
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import realm, viewer_of
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: What the realm's authorize request carries, and the form hands back on POST.
_FLOW = ("state", "nonce", "redirect_uri")


def favicon(request: HttpRequest) -> HttpResponse:
    return HttpResponseNotFound()


def _viewer_from_post(request: HttpRequest) -> Archivist | Member | None:
    kind = request.POST.get("kind", "")
    if kind == "archivist":
        username = request.POST.get("username", "").strip()
        return Archivist(username=username) if username else Archivist()
    if kind == "member":
        raw = request.POST.get("groups", "")
        return Member(groups=tuple(raw.replace(",", " ").split()))
    return None


def _flow(params: QueryDict) -> dict[str, str]:
    return {name: params.get(name, "") for name in _FLOW}


def authorize(request: HttpRequest) -> HttpResponse:
    """GET renders the login form for one login; POST answers it with a code for the chosen viewer,
    back at ``redirect_uri``. That must be this site's own callback, so the page redirects nowhere
    else. A GET without a login (a bookmark) starts one."""
    if request.method == "POST":
        return _answer(request)
    if request.method != "GET":
        return not_found()
    flow = _flow(request.GET)
    if not all(flow.values()):
        return HttpResponseRedirect(login_redirect("/"))
    if flow["redirect_uri"] != callback_uri(request):
        return not_found()
    return HttpResponse(_render_form(viewer_of(request), flow, csrf_token=get_token(request)))


def _answer(request: HttpRequest) -> HttpResponse:
    flow = _flow(request.POST)
    viewer = _viewer_from_post(request)
    if not all(flow.values()) or flow["redirect_uri"] != callback_uri(request) or viewer is None:
        return not_found()
    login_realm = realm()
    if not isinstance(login_realm, DevRealm):
        return not_found()
    code = login_realm.mint_code(claims_of(viewer), nonce=flow["nonce"])
    if code is None:
        return not_found()
    answer = urlencode({"code": code, "state": flow["state"]})
    return HttpResponseRedirect(f"{flow['redirect_uri']}?{answer}")


def _describe(viewer: Viewer) -> str:
    """Human-readable German label for the currently active viewer (shown at the top of the form)."""
    match viewer:
        case Archivist(username=username):
            return f"Archivar {username} (sieht alles)"
        case Member(groups=groups):
            return "Mitglied — Gruppen: " + (", ".join(groups) if groups else "(keine)")
        case Public():
            return "Öffentlich (nicht angemeldet)"


def _render_form(current: Viewer, flow: dict[str, str], *, csrf_token: str) -> str:
    hidden = "".join(
        f'<input type=hidden name={name} value="{escape(value)}">' for name, value in flow.items()
    )
    return (
        "<!doctype html><html lang=de><head><meta charset=utf-8>"
        '<link rel="stylesheet" href="/static/tokens.css">'
        '<link rel="stylesheet" href="/static/components.css">'
        '<link rel="stylesheet" href="/static/layouts.css">'
        "<title>Dev: Anmelden</title></head><body>"
        '<main class="stub">'
        "<h1>Anmelden als (nur Entwicklung)</h1>"
        f"<p>Aktuell: <strong>{escape(_describe(current))}</strong></p>"
        f'<form method=post action="{reverse("dev-authorize")}">'
        f'<input type=hidden name=csrfmiddlewaretoken value="{escape(csrf_token)}">{hidden}'
        "<p><label><input type=radio name=kind value=archivist> Archivar</label>"
        " Benutzername: <input type=text name=username></p>"
        "<p><label><input type=radio name=kind value=member checked> Mitglied</label>"
        ' Gruppen: <input type=text name=groups placeholder="gruppe1, gruppe2"></p>'
        '<p><button class="primary" type=submit>Anmelden</button></p>'
        "</form></main></body></html>"
    )
