"""Tests for the structured (JSON) logging setup -- apm_connectors used
no logging module at all before this, so these just prove the formatter
produces valid, parseable JSON with the fields callers rely on (extra
fields, exception tracebacks) rather than testing Python's own logging
plumbing.
"""

from __future__ import annotations

import json
import logging

from apm_connectors.logging_config import JsonFormatter, configure_logging


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="apm_connectors.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_valid_json_with_core_fields() -> None:
    record = _make_record()
    parsed = json.loads(JsonFormatter().format(record))

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "apm_connectors.api"
    assert parsed["message"] == "request"
    assert "timestamp" in parsed


def test_extra_fields_surface_as_top_level_keys() -> None:
    record = _make_record(process_id="order-1", status_code=200, duration_ms=4.2)
    parsed = json.loads(JsonFormatter().format(record))

    assert parsed["process_id"] == "order-1"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 4.2


def test_exception_info_is_captured() -> None:
    try:
        raise RuntimeError("simulated failure")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            name="apm_connectors.api",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="upstream tool error",
            args=(),
            exc_info=sys.exc_info(),
        )
    parsed = json.loads(JsonFormatter().format(record))

    assert "simulated failure" in parsed["exception"]


def test_configure_logging_is_idempotent() -> None:
    configure_logging()
    configure_logging()
    root = logging.getLogger()

    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
