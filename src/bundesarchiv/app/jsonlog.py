"""One JSON object per log record, for stdout (app, worker and gunicorn alike).

Every key passed through ``extra={...}`` becomes a top-level field; ``timestamp``, ``level``,
``logger`` and ``message`` are always present and win a clash. A traceback is the string field
``exc_info``, so a record stays one line. Values JSON cannot encode are written as their ``str``.
"""

import json
import logging
from datetime import UTC, datetime

# Everything a LogRecord carries itself; what is left in its __dict__ came in through `extra`.
_OWN = {*logging.LogRecord("", 0, "", 0, "", (), None).__dict__, "message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, object] = {k: v for k, v in record.__dict__.items() if k not in _OWN}
        fields |= {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Django's request log passes the request itself; its repr carries the query string (search
        # terms, the OIDC code), so only the method and path reach the log.
        if (request := fields.get("request")) is not None and hasattr(request, "path"):
            fields["request"] = f"{getattr(request, 'method', '')} {request.path}".strip()
        if record.exc_info:
            fields["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            fields["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(fields, default=str, ensure_ascii=False)
