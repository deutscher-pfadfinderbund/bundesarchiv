"""``render_screen`` — the single authority for the shared header's authorization facts.

``is_archivist`` and ``is_signed_in`` gate chrome (the "+ Neu …" create disclosure, Abmelden), so
they are authorization-shaped: the helper resolves both from ``viewer_of`` and no caller context may
assert them. The leak matrix asserts route gates and never chrome, so this is the only gate on that.

DB-free: a ``RequestFactory`` request with no cookie floors to ``Public()``, and the shared header
partial is rendered on its own — the smallest surface that carries both gates.
"""

from django.http import HttpRequest
from django.test import RequestFactory

from bundesarchiv.app.web.viewers import render_screen

_HEADER = "workbench/_header.html"


def _render_header(context: dict[str, object]) -> str:
    request: HttpRequest = RequestFactory().get("/")
    return render_screen(request, _HEADER, context).content.decode()


def test_caller_context_cannot_assert_archivist_chrome() -> None:
    assert "Neuer Artikel" not in _render_header({"is_archivist": True})


def test_caller_context_cannot_assert_signed_in_chrome() -> None:
    assert "Abmelden" not in _render_header({"is_signed_in": True})
