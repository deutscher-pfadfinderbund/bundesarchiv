"""``request_kind`` — the one reader of the ``HX-`` request headers. A history restore must never
read as a partial, whether htmx 4 (restore header alone) or htmx 2 (both headers) sent it."""

import pytest
from django.test import Client, RequestFactory, override_settings

from bundesarchiv.app.web.viewers import RequestKind, request_kind


@pytest.mark.parametrize(
    ("headers", "kind"),
    [
        ({}, RequestKind.PAGE),
        ({"HX-Request": "true"}, RequestKind.PARTIAL),
        ({"HX-History-Restore-Request": "true"}, RequestKind.RESTORE),
        (
            {"HX-Request": "true", "HX-History-Restore-Request": "true"},
            RequestKind.RESTORE,
        ),
    ],
)
def test_request_kind(headers: dict[str, str], kind: RequestKind) -> None:
    assert request_kind(RequestFactory().get("/", headers=headers)) is kind


@pytest.mark.parametrize("gate", [False, True], ids=["page", "door"])
@pytest.mark.parametrize("headers", [{}, {"HX-Request": "true"}], ids=["plain", "htmx"])
def test_every_response_varies_on_the_request_kind(gate: bool, headers: dict[str, str]) -> None:
    with override_settings(ANONYMOUS_GATE_ENABLED=gate):
        response = Client().get("/nichts-dergleichen", headers=headers)
    vary = response.headers["Vary"]
    assert "HX-Request" in vary
    assert "HX-History-Restore-Request" in vary
