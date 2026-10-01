"""Slow requests: one WARNING record per request that took longer than
``BUNDESARCHIV_SLOW_REQUEST_MS``. It names the route, never the path (the path carries ULIDs).
Media bytes nginx serves through X-Accel are skipped: the response returns at once and the
transfer is not ours."""

import logging
import time
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase

logger = logging.getLogger(__name__)


class SlowRequestMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        started = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - started) * 1000)
        if (
            duration_ms > settings.BUNDESARCHIV_SLOW_REQUEST_MS
            and "X-Accel-Redirect" not in response
        ):
            match = request.resolver_match
            logger.warning(
                "slow request",
                extra={
                    "route": match.view_name if match else "unresolved",
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        return response
