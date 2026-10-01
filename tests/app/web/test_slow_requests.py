"""The slow-request record: the route name and the timing, never the path."""

import itertools
import time

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import resolve

from bundesarchiv.app.web import slow_requests
from bundesarchiv.app.web.slow_requests import SlowRequestMiddleware


def _serve(
    monkeypatch: pytest.MonkeyPatch, seconds: float, *, headers: dict[str, str] | None = None
) -> None:
    """Run one request to a ULID path that took `seconds`."""
    ticks = itertools.cycle([0.0, seconds])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    request = RequestFactory().get("/collections/01ABCDEF/edit")
    request.resolver_match = resolve(request.path)

    def view(_: HttpRequest) -> HttpResponse:
        return HttpResponse(status=200, headers=headers)

    with override_settings(BUNDESARCHIV_SLOW_REQUEST_MS=1000):
        SlowRequestMiddleware(view)(request)


def test_a_slow_request_logs_its_route_name_not_its_path(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING", logger=slow_requests.__name__):
        _serve(monkeypatch, 1.5)
    (record,) = caplog.records
    fields = vars(record)
    assert (fields["route"], fields["method"], fields["status"], fields["duration_ms"]) == (
        "bestand-bearbeiten",
        "GET",
        200,
        1500,
    )
    assert "01ABCDEF" not in str(fields)


@pytest.mark.parametrize(
    ("seconds", "headers"),
    [(0.2, None), (3.0, {"X-Accel-Redirect": "/protected/x"})],
    ids=["fast", "x-accel"],
)
def test_a_fast_request_and_an_x_accel_media_response_log_nothing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    seconds: float,
    headers: dict[str, str] | None,
) -> None:
    with caplog.at_level("WARNING", logger=slow_requests.__name__):
        _serve(monkeypatch, seconds, headers=headers)
    assert not caplog.records
