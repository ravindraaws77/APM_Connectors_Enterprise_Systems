"""Structured (JSON) operational logging, shared by the API server and
any script that wants machine-parseable logs instead of Python's default
plain-text formatting.

This is not the audit trail (state/store.py) and never replaces it --
that stays the system of record for "what happened to this process"
(read/proposed/approved/rejected/executed/failed), queried by
process_id long after a log line has scrolled off. This module is for
"what did the server do": request handling, startup, and unexpected
failures -- previously nothing in this package used Python's `logging`
module at all, relying entirely on the audit trail plus uvicorn's own
default (unstructured) traceback dump on a 502.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

# Every attribute a bare LogRecord already carries, so `_extra_fields`
# below only surfaces what a caller actually attached via `extra=...`.
_RESERVED_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger name, message,
    the exception traceback (if any), and any `extra={...}` fields a
    caller attached to the record -- e.g.
    `logger.error("...", extra={"process_id": pid, "tool": tool})`.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """Installs the JSON formatter on the root logger. Idempotent -- safe
    to call more than once (app startup, a test fixture) without
    stacking duplicate handlers. `level` defaults to the `APM_LOG_LEVEL`
    env var, then "INFO".
    """
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("APM_LOG_LEVEL", "INFO"))
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
