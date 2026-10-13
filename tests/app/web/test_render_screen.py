"""The only gate on the header's authorization-shaped chrome: the leak matrix checks routes, not
chrome."""

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
