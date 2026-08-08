"""``viewer_of(request) -> Viewer`` — THE request→Viewer trust boundary (Part 4.4).

ONE function the whole web layer calls to answer *who is asking* (domain ``Viewer``: Archivist |
Member(groups) | Public). Part 5 re-implements this same seam against OIDC/Keycloak claims — one
seam, two adapters; the UI code above never knows which is wired.

The Part 4 adapter reads a SIGNED cookie set by the dev-only switcher (``dev`` module). The cookie
is verified with a DEDICATED dev-only signing key (``DEV_VIEWER_SIGNING_KEY``, defined only in
``settings_dev``) — NEVER the production ``SECRET_KEY`` — so a leaked/replayed dev cookie is
worthless against any production deployment, and under production settings (which define no such
key) this seam simply falls closed.

Fail-closed everywhere: no cookie, no dev key configured, a tampered/expired signature, or a
payload that does not parse to a known viewer shape ALL resolve to ``Public()``. A bad cookie is
never an error — only ever an anonymous viewer.
"""

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

#: Name of the signed cookie the dev switcher sets and this seam reads.
DEV_VIEWER_COOKIE = "dev_viewer"

#: Signer salt namespacing the dev-viewer cookie (kept separate from any other signed value).
_DEV_VIEWER_SALT = "dev-viewer"

#: How long a dev-viewer cookie stays valid (12h — a working day; expired ones fall back to Public).
_DEV_VIEWER_MAX_AGE = 12 * 60 * 60


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
    ``archivist`` | ``member:group1,group2`` | ``public``. Groups are comma-joined; a Member with
    no groups encodes as a bare ``member`` (empty group list)."""
    match viewer:
        case Archivist():
            return "archivist"
        case Member(groups=groups):
            return "member:" + ",".join(groups) if groups else "member"
        case Public():
            return "public"


def _parse_viewer(payload: str) -> Viewer | None:
    """Parse a verified cookie payload back to a ``Viewer``, or ``None`` if it is not a known shape.
    STRICT: only the exact vocabulary ``archivist`` / ``public`` / ``member`` / ``member:<groups>``
    is accepted; anything else (a signed-but-garbage payload) yields ``None`` so the caller floors
    to Public. Empty group entries are dropped so ``member:a,,b`` -> groups ``(a, b)``."""
    if payload == "archivist":
        return Archivist()
    if payload == "public":
        return Public()
    if payload == "member":
        return Member(groups=())
    if payload.startswith("member:"):
        groups = tuple(g for g in payload.removeprefix("member:").split(",") if g)
        return Member(groups=groups)
    return None


def viewer_of(request: HttpRequest) -> Viewer:
    """Resolve the request's ``Viewer`` — the single web-layer trust boundary. Returns ``Public()``
    unless a dev-viewer cookie is present, correctly signed with the dedicated dev key, unexpired,
    and parses to a known viewer shape. Every failure mode falls closed to ``Public()``; a bad
    cookie never raises."""
    signer = _dev_signer()
    if signer is None:
        return Public()
    raw = request.COOKIES.get(DEV_VIEWER_COOKIE)
    if not raw:
        return Public()
    try:
        payload = signer.unsign(raw, max_age=_DEV_VIEWER_MAX_AGE)
    except signing.BadSignature:
        return Public()
    return _parse_viewer(payload) or Public()


def render_screen(request: HttpRequest, template: str, context: dict[str, object]) -> HttpResponse:
    """Render a screen with ``is_archivist`` resolved HERE, from ``viewer_of``.

    The shared header's "+ Neu …" create disclosure is ARCHIVIST CHROME, so whether it renders is an
    authorization-shaped fact — and an authorization fact is the view's to decide, exactly as
    ``browse_views`` decides it for the workbench and the detail reader. Four include sites used to
    ASSERT it (``{% include "workbench/_header.html" with is_archivist=True %}``) on the grounds that
    their routes are archivist-gated. True today, and unfalsifiable by the leak matrix, which asserts
    route gates and never chrome: the day a screen with this header is reached by a lower tier — a
    member-facing Lesesaal composition, a capability-link surface — the template would hand out
    archivist chrome without a word. One helper, and the fact comes from the viewer everywhere.

    Any ``is_archivist`` the caller already put in ``context`` wins, so a view that computed the same
    fact for other purposes stays the one source on its own screen."""
    return render(request, template, {"is_archivist": _is_archivist(request), **context})


def _is_archivist(request: HttpRequest) -> bool:
    """Whether the request's viewer is an Archivist — the presentation gate for archivist chrome and
    the route gate for every cataloging route."""
    return isinstance(viewer_of(request), Archivist)
