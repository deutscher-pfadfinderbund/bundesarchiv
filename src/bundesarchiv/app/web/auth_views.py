"""The login surface: ``GET /login``, ``GET /oidc/callback``, ``POST /logout`` (ADR 0018).

The three routes that turn a Keycloak login into the two token cookies ``viewer_of`` resolves — no
Django sessions, no user model; the server stores no token. There is no login PAGE and no
Abmelden landing page (owner, 2026-08-29): ``/login`` IS the redirect to Keycloak, and a logout
lands back on the workbench as an anonymous visitor.

Everything that touches the realm goes through the ``keycloak`` seams imported here as module
names — the suite fakes them in place (the web subtree's boundary-stub pattern) and everything else
in this module runs for real.

Fail-closed, in the shape the rest of the surface uses: a missing signing key, an unreachable realm,
a callback nobody's ``/login`` started, a token exchange that failed — all the shared empty 404. Two
deliberate exceptions, both because the alternative is worse than the deny: ``/logout`` always clears
the local cookies (refusing to sign somebody OUT is not a safe failure), and a callback whose VERIFIED
transient carries another state restarts the login instead of stranding a stale tab on a blank page.
"""

from dataclasses import dataclass
from secrets import compare_digest, token_urlsafe
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from bundesarchiv.app.web.keycloak import authorization_url, fetch_tokens, logout_url
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import (
    REFRESH_COOKIE,
    delete_token_cookies,
    set_token_cookies,
)

#: The short-lived cookie carrying one login's ``state``/``nonce``/``next`` across the redirect to
#: Keycloak and back. Signed with the viewer key under its OWN salt; it is transient by design and
#: the callback drops it, so one cookie serves exactly one login. ``__Host-`` because Keycloak lives
#: on a sibling host, and no sibling host may shadow it.
STATE_COOKIE = "__Host-oidc_state"

_STATE_SALT = "oidc-state"

#: How long a started login may take to come back. Long enough for a password manager and a second
#: factor, short enough that an abandoned login leaves nothing usable behind.
_STATE_MAX_AGE = 10 * 60

#: 32 bytes of entropy each for ``state`` (CSRF binding) and ``nonce`` (ID-token replay binding).
_TOKEN_BYTES = 32

#: Where a login lands when it carries no usable ``?next=``.
_DEFAULT_NEXT = "/"


@dataclass(frozen=True, slots=True)
class _Transient:
    """One in-flight login: the two values the response must match, plus where to land."""

    state: str
    nonce: str
    next_path: str


def safe_next(raw: str | None) -> str | None:
    """The same-origin landing path in ``raw``, or ``None`` if it is anything else.

    A whitelist of SHAPE, not a blacklist of hosts: an absolute URL, a scheme-relative ``//host``,
    the backslash variants browsers normalize into one (``/\\host``), and any control character (a
    ``\\r\\n`` would split the Location header) are all simply not the shape of a local path."""
    if not raw or not raw.startswith("/") or raw.startswith(("//", "/\\")):
        return None
    if "\\" in raw or any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return None
    return raw


def _callback_uri(request: HttpRequest) -> str:
    """The absolute callback URL — it must match the realm client's registered redirect URI exactly,
    and Keycloak checks that the token exchange repeats the one the authorize request used."""
    return request.build_absolute_uri(reverse("oidc-callback"))


def login(request: HttpRequest) -> HttpResponse:
    """``GET /login`` — start the code flow: mint a state/nonce pair, remember them (with the
    landing path) in the transient cookie, and hand the browser to Keycloak. Also the target the
    anonymous gate redirects to, hence the ``?next=``."""
    key = settings.VIEWER_SIGNING_KEY
    if request.method != "GET" or not key:
        return _not_found()
    state, nonce = token_urlsafe(_TOKEN_BYTES), token_urlsafe(_TOKEN_BYTES)
    url = authorization_url(state=state, nonce=nonce, redirect_uri=_callback_uri(request))
    if url is None:
        return _not_found()
    payload = {
        "state": state,
        "nonce": nonce,
        "next": safe_next(request.GET.get("next")) or _DEFAULT_NEXT,
    }
    response = HttpResponseRedirect(url)
    response.set_cookie(
        STATE_COOKIE,
        signing.dumps(payload, key=key, salt=_STATE_SALT),
        max_age=_STATE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="Lax",
    )
    return response


def _transient_of(request: HttpRequest) -> _Transient | None:
    """The in-flight login this request belongs to, or ``None`` when there is no verified one —
    absent, expired, tampered, signed with another key, or not the shape we wrote."""
    key = settings.VIEWER_SIGNING_KEY
    raw = request.COOKIES.get(STATE_COOKIE)
    if not key or not raw:
        return None
    try:
        payload = signing.loads(raw, key=key, salt=_STATE_SALT, max_age=_STATE_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    state, nonce = payload.get("state"), payload.get("nonce")
    if not isinstance(state, str) or not isinstance(nonce, str):
        return None
    landing = payload.get("next")
    # Re-validated on the way OUT too: this cookie is ours and signed, so it costs one call to make
    # the landing path unable to become an open redirect through some future writer's shortcut.
    landing = safe_next(landing) if isinstance(landing, str) else None
    return _Transient(state, nonce, landing or _DEFAULT_NEXT)


def oidc_callback(request: HttpRequest) -> HttpResponse:
    """``GET /oidc/callback`` — Keycloak's answer: match the state, exchange the code for checked
    tokens, set the two token cookies, and land on the remembered path."""
    if request.method != "GET":
        return _not_found()
    transient = _transient_of(request)
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    if transient is None or not code or not state:
        return _not_found()
    # Encoded, not compared as text: compare_digest REFUSES a non-ASCII str, and this one is the
    # attacker's to choose — a raw comparison answers `?state=ü` with a 500.
    if not compare_digest(state.encode(), transient.state.encode()):
        # A verified transient whose state is another tab's: the second /login overwrote this
        # cookie. That is a stale login, not an attack — send them back through the flow rather
        # than onto a dead 404. It terminates: the restart mints the state it will match.
        return HttpResponseRedirect(login_redirect(transient.next_path))
    tokens = fetch_tokens(code=code, nonce=transient.nonce, redirect_uri=_callback_uri(request))
    if tokens is None:
        return _not_found()
    response = HttpResponseRedirect(transient.next_path)
    set_token_cookies(tokens, response)
    response.delete_cookie(STATE_COOKIE)
    return response


def logout(request: HttpRequest) -> HttpResponse:
    """``POST /logout`` — end the Keycloak session as far as the server can (``logout_url``), drop
    the token cookies, and continue through Keycloak's end-session endpoint (ADR 0018 "Logout").
    With no realm to return through, the cookies still go."""
    if request.method != "POST":
        return _not_found()
    home = request.build_absolute_uri(_DEFAULT_NEXT)
    url = logout_url(
        refresh_token=request.COOKIES.get(REFRESH_COOKIE), post_logout_redirect_uri=home
    )
    response = HttpResponseRedirect(url or _DEFAULT_NEXT)
    delete_token_cookies(response)
    return response


def login_redirect(next_path: str) -> str:
    """The ``/login?next=…`` URL that sends a visitor through the login and back to ``next_path``.
    Here rather than in the caller, so the query parameter's name is known in ONE module."""
    return f"{reverse('login')}?{urlencode({'next': next_path})}"
