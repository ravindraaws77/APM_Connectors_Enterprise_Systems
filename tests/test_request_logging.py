"""Confirms api/app.py's request-logging middleware actually fires and
logs the fields a log aggregator would filter/group on. Patches the
module's logger directly rather than going through caplog, since
create_app() calls configure_logging() (api/logging_config.py), which
replaces the root logger's handlers -- that would also clobber caplog's
own handler if it ran first.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apm_connectors.api import app as app_module
from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_state_store, get_tools


class _FakeStore:
    def list_processes(self) -> list:
        return []


def test_request_middleware_logs_structured_fields(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(app_module.logger, "info", lambda msg, extra=None: calls.append((msg, extra)))

    app = create_app()
    # /health now actually checks the state store and every configured
    # tool (see app.py) -- override both so this test doesn't need a real
    # DATABASE_URL just to exercise the logging middleware.
    app.dependency_overrides[get_state_store] = lambda: _FakeStore()
    app.dependency_overrides[get_tools] = lambda: {}
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


def test_request_middleware_correlates_by_process_id_from_the_body(monkeypatch, tmp_path: Path) -> None:
    """A /tools/* POST body's process_id (now case_id, once
    apm_orchestrator threads it through -- see that repo's case_graph.py)
    shows up on this server's own structured request log, so the two can
    be joined without a full distributed trace."""
    from apm_connectors.state.store import StateStore
    from apm_connectors.tools.gmail_tool import GmailTool
    from tests.test_gmail_tool import FakeGmailClient

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(app_module.logger, "info", lambda msg, extra=None: calls.append((msg, extra)))

    app = create_app()
    store = StateStore(tmp_path / "state.json")
    app.dependency_overrides[get_state_store] = lambda: store
    app.dependency_overrides[get_tools] = lambda: {"gmail": GmailTool(store, FakeGmailClient([]))}
    client = TestClient(app)

    response = client.post("/tools/gmail/search", json={"process_id": "order-42", "query": "renewal"})

    assert response.status_code == 200
    message, extra = calls[0]
    assert message == "request"
    assert extra["path"] == "/tools/gmail/search"
    assert extra["process_id"] == "order-42"
