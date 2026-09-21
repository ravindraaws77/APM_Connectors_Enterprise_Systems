"""Tests for GET /health actually checking the state store and every
configured connector, instead of the static {"status": "ok"} it used to
return regardless of whether the server could serve anything. See
app.py's health() docstring for why a dead state store is a 503 but an
unhealthy connector is a 200 "degraded" instead.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_state_store, get_tools
from apm_connectors.state.store import StateStore
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_gmail_tool import BrokenGmailClient, FakeGmailClient


class _BrokenStore:
    def list_processes(self) -> list:
        raise RuntimeError("connection refused")


def test_health_is_unhealthy_and_503_when_the_state_store_is_down() -> None:
    app = create_app()
    app.dependency_overrides[get_state_store] = lambda: _BrokenStore()
    app.dependency_overrides[get_tools] = lambda: {}
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["state_store"] is False


def test_health_is_degraded_but_200_when_one_tool_is_unhealthy(tmp_path: Path) -> None:
    """A live state store but one bad connector credential must not take
    the whole server out of a load balancer's rotation -- every OTHER
    connector (and every non-tools route) still works."""
    app = create_app()
    store = StateStore(tmp_path / "state.json")
    app.dependency_overrides[get_state_store] = lambda: store
    app.dependency_overrides[get_tools] = lambda: {
        "gmail": GmailTool(store, FakeGmailClient([])),
        "jira": GmailTool(store, BrokenGmailClient()),  # stands in for any unhealthy connector
    }
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["state_store"] is True
    assert body["tools"] == {"gmail": True, "jira": False}


def test_health_is_ok_when_everything_is_healthy(tmp_path: Path) -> None:
    app = create_app()
    store = StateStore(tmp_path / "state.json")
    app.dependency_overrides[get_state_store] = lambda: store
    app.dependency_overrides[get_tools] = lambda: {"gmail": GmailTool(store, FakeGmailClient([]))}
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "state_store": True, "tools": {"gmail": True}}
