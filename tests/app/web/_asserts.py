"""Shared response assertions for the web suite: the deny, the anonymous gate's bounce and its door.

The single definition of what a deny looks like over HTTP, so every per-route test pins the
same contract and there is ONE edit point if it ever changes (e.g. when a styled access-denied
page ships). Relaxed from the byte-identical-404 law (owner ruling 2026-08, see
docs/requirements/owner-interview-2026-08.md): the byte-for-byte shape comparison is gone;
what remains is that a deny is a 404 whose body reveals nothing — production emits the one
constant ``404.html`` page from ``not_found()``, rendered once, so the body is the same for every
reason and every viewer.
"""

import re
from collections.abc import Sequence
from html import unescape
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from django.template.base import Template
from django.template.loader import render_to_string


class _Response(Protocol):
    """The two fields a deny assert reads — covers HttpResponse and the test client's response."""

    status_code: int
    content: bytes


class _Rendered(_Response, Protocol):
    """A test client response, which also records the templates it rendered."""

    @property
    def templates(self) -> Sequence[Template]: ...


def assert_denied(response: _Response, ctx: str = "") -> None:
    """A deny/absence response: status 404 and exactly the one constant 404 page (nothing revealed)."""
    label = f" [{ctx}]" if ctx else ""
    assert response.status_code == 404, f"expected a 404 deny{label}, got {response.status_code}"
    assert response.content == render_to_string("404.html").encode(), (
        f"a deny must be the one constant 404 page{label}"
    )


def assert_login_target(url: str, next_path: str, ctx: str = "") -> None:
    """The anonymous gate's bounce target (ADR 0018): the login route, carrying the path the
    visitor was going to. Takes the URL apart instead of re-spelling production's percent encoding
    by hand — the spelling is not the contract, and a second encoder drifts from the first."""
    label = f" [{ctx}]" if ctx else ""
    target = urlsplit(url)
    assert target.path == "/login", f"expected the login route{label}, got {url}"
    assert parse_qs(target.query).get("next") == [next_path], (
        f"the login target must carry next={next_path}{label}, got {url}"
    )


_LOGIN_HREF = re.compile(r'href="(/login\?[^"]*)"')
_CSRF_TOKEN = re.compile(r'"X-CSRFToken": "[^"]*"')


def assert_door(response: _Rendered, next_path: str, ctx: str = "") -> str:
    """The anonymous gate's door (ADR 0018): a 200 whose one login link carries ``next_path``.
    Returns the page with that link's target and the per-request CSRF token cut out, so a caller
    can compare two doors: the token is random per request, never derived from the path."""
    label = f" [{ctx}]" if ctx else ""
    assert response.status_code == 200, f"expected the door{label}, got {response.status_code}"
    assert "workbench/door.html" in [t.name for t in response.templates], f"not the door{label}"
    html = response.content.decode()
    (href,) = _LOGIN_HREF.findall(html)
    assert_login_target(unescape(href), next_path, ctx)
    return _CSRF_TOKEN.sub("", html.replace(href, ""))
