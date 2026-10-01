"""The log format: one record is one JSON line (``bundesarchiv.app.jsonlog``)."""

import io
import json
import logging

from bundesarchiv.app.jsonlog import JsonFormatter


def _emit(log: logging.Logger, message: str, **kwargs: object) -> list[str]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    try:
        log.error(message, **kwargs)  # type: ignore[arg-type]
    finally:
        log.removeHandler(handler)
    return stream.getvalue().splitlines()


def test_a_record_is_one_json_line_with_the_base_fields_and_the_extras() -> None:
    log = logging.getLogger("jsonlog.test.extra")
    (line,) = _emit(log, "pushed 3", extra={"sent": 3, "keys": ["a", "b"], "level": "spoofed"})
    record = json.loads(line)
    assert record["message"] == "pushed 3"
    assert (record["level"], record["logger"]) == ("ERROR", "jsonlog.test.extra")
    assert record["timestamp"].endswith("+00:00")
    assert (record["sent"], record["keys"]) == (3, ["a", "b"])


def test_a_traceback_stays_inside_its_record() -> None:
    log = logging.getLogger("jsonlog.test.trace")
    try:
        raise ValueError("boom\nsecond line")
    except ValueError:
        lines = _emit(log, "failed", exc_info=True)
    (line,) = lines
    assert "ValueError: boom" in json.loads(line)["exc_info"]


def test_a_value_json_cannot_encode_is_written_as_its_str() -> None:
    (line,) = _emit(logging.getLogger("jsonlog.test.str"), "x", extra={"obj": {1, 2}})
    assert json.loads(line)["obj"] == str({1, 2})


def test_a_logged_request_keeps_its_path_and_drops_its_query() -> None:
    from django.test import RequestFactory

    request = RequestFactory().get("/oidc/callback?code=SECRET&state=S")
    record = logging.LogRecord("django.request", logging.WARNING, "", 0, "Not Found", (), None)
    record.request = request
    line = JsonFormatter().format(record)
    assert json.loads(line)["request"] == "GET /oidc/callback"
    assert "SECRET" not in line
