"""Tests for GET /metrics -- both render_metrics() directly (the text
it produces) and that the route is wired in and auth-gated like every
other /processes*//tools* route (never /health).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apm_connectors.api import dependencies as dependencies_module
from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_state_store, get_tools
from apm_connectors.api.metrics import render_metrics
from apm_connectors.state.store import StateStore
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_gmail_tool import BrokenGmailClient, FakeGmailClient


def test_render_metrics_counts_pending_actions_by_tool(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.add_pending_action("order-1", tool="gmail", description="Send", payload={})
    store.add_pending_action("order-2", tool="gmail", description="Send", payload={})
    store.add_pending_action("order-3", tool="jira", description="Create", payload={})
    tools = {"gmail": GmailTool(store, FakeGmailClient([]))}

    text = render_metrics(store, tools)

    assert "apm_pending_actions_total 3" in text
    assert 'apm_pending_actions_by_tool{tool="gmail"} 2' in text
    assert 'apm_pending_actions_by_tool{tool="jira"} 1' in text
    assert 'apm_connector_healthy{tool="gmail"} 1' in text
    assert "apm_processes_total" in text


def test_render_metrics_reports_an_unhealthy_connector(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tools = {"gmail": GmailTool(store, BrokenGmailClient())}

    text = render_metrics(store, tools)

    assert 'apm_connector_healthy{tool="gmail"} 0' in text


def test_metrics_route_is_gated_like_processes_not_like_health(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})
    app = create_app()
    store = StateStore(tmp_path / "state.json")
    app.dependency_overrides[get_state_store] = lambda: store
    app.dependency_overrides[get_tools] = lambda: {"gmail": GmailTool(store, FakeGmailClient([]))}
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    response = client.get("/metrics", headers={"Authorization": "Bearer sk_abc123"})
    assert response.status_code == 200
    assert "apm_pending_actions_total 0" in response.text
