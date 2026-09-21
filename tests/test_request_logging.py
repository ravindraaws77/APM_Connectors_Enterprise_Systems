"""Confirms api/app.py's request-logging middleware actually fires and
logs the fields a log aggregator would filter/group on. Patches the
module's logger directly rather than going through caplog, since
create_app() calls configure_logging() (api/logging_config.py), which
replaces the root logger's handlers -- that would also clobber caplog's
own handler if it ran first.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apm_connectors.api import app as app_module
from apm_connectors.api.app import create_app


def test_request_middleware_logs_structured_fields(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(app_module.logger, "info", lambda msg, extra=None: calls.append((msg, extra)))

    app = create_app()
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert len(calls) == 1
    message, extra = calls[0]
    assert message == "request"
    assert extra["method"] == "GET"
    assert extra["path"] == "/health"
    assert extra["status_code"] == 200
    assert isinstance(extra["duration_ms"], float)
