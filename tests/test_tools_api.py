"""Tests for the /tools/* routes (apm_connectors.api.tools_routes) — the direct
per-tool read/write API, with no reasoning involved. Uses the real tools
wired to fake clients (same fixtures as tests/test_api.py), injected via
FastAPI's dependency_overrides, so no live credentials are needed.

Covers: reads return data immediately; a write pauses for approval and
does not execute until POST /tools/actions/{id}/decision approves it;
rejecting doesn't execute; a tool that isn't configured on this server
returns a clean 503 rather than a crash.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from apm_connectors.graph import build_action_graph
from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_action_graph, get_tools
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.excel_file_tool import ExcelFileTool
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes
from tests.test_gmail_tool import FakeGmailClient, _raw_message


def _client(tmp_path: Path, with_excel: bool = True, gmail_messages: list | None = None):
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient(gmail_messages or [])
    calendar_client = FakeCalendarClient([])
    tools = {
        "gmail": GmailTool(store, gmail_client),
        "google_calendar": CalendarTool(store, calendar_client),
    }
    excel_source = None
    if with_excel:
        excel_source = FakeWorkbookSource(_sample_workbook_bytes())
        tools["excel_file"] = ExcelFileTool(store, excel_source)
    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_action_graph] = lambda: action_graph
    return TestClient(app), store, gmail_client, calendar_client, excel_source


# -- reads --------------------------------------------------------------


def test_gmail_search_returns_data_immediately(tmp_path: Path) -> None:
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    client, store, gmail_client, _, _ = _client(tmp_path, gmail_messages=[message])

    response = client.post("/tools/gmail/search", json={"process_id": "order-1", "query": "newer_than:7d"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["subject"] == "Hi"
    # A read is logged for the audit trail same as any other tool call.
    assert any(e["event_type"] == "read" for e in store.list_events("order-1"))


def test_excel_worksheets_read(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path)
    response = client.post("/tools/excel/worksheets", json={"process_id": "order-1"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


def test_unconfigured_tool_returns_503(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, with_excel=False)
    response = client.post("/tools/excel/worksheets", json={"process_id": "order-1"})
    assert response.status_code == 503


# -- writes: propose -> approve/reject -----------------------------------


def test_gmail_send_pauses_for_approval_then_executes(tmp_path: Path) -> None:
    client, store, gmail_client, _, _ = _client(tmp_path)

    propose = client.post(
        "/tools/gmail/send",
        json={"process_id": "order-2", "to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
    )
    assert propose.status_code == 200
    body = propose.json()
    assert body["pending_action"] is not None
    assert body["pending_action"]["tool"] == "gmail"
    assert body["final_result"] is None
    assert gmail_client.sent == []
    assert len(store.list_pending_actions("order-2")) == 1

    decide = client.post("/tools/actions/order-2/decision", json={"approved": True})
    assert decide.status_code == 200
    outcome = decide.json()
    assert outcome["final_result"]["executed"] is True
    assert len(gmail_client.sent) == 1
    assert store.list_pending_actions("order-2") == []


def test_gmail_send_rejected_does_not_execute(tmp_path: Path) -> None:
    client, store, gmail_client, _, _ = _client(tmp_path)
    client.post(
        "/tools/gmail/send",
        json={"process_id": "order-3", "to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
    )

    decide = client.post("/tools/actions/order-3/decision", json={"approved": False})

    assert decide.status_code == 200
    assert decide.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert gmail_client.sent == []
    assert store.list_pending_actions("order-3") == []


def test_calendar_create_event_gated(tmp_path: Path) -> None:
    client, store, _, calendar_client, _ = _client(tmp_path)

    propose = client.post(
        "/tools/calendar/create-event",
        json={"process_id": "order-4", "title": "Renewal call", "start": "2026-09-10T15:00:00Z", "end": "2026-09-10T15:30:00Z"},
    )
    assert propose.status_code == 200
    assert calendar_client.inserted == []

    decide = client.post("/tools/actions/order-4/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(calendar_client.inserted) == 1


def test_excel_write_gated(tmp_path: Path) -> None:
    client, store, _, _, excel_source = _client(tmp_path)

    propose = client.post(
        "/tools/excel/write",
        json={"process_id": "order-5", "sheet_name": "Renewals", "address": "A1:A1", "values": [["done"]]},
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["tool"] == "excel_file"

    decide = client.post("/tools/actions/order-5/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True


def test_write_to_unconfigured_tool_returns_503_without_creating_a_pending_action(tmp_path: Path) -> None:
    client, store, *_ = _client(tmp_path, with_excel=False)

    response = client.post(
        "/tools/excel/write",
        json={"process_id": "order-6", "sheet_name": "Sheet1", "address": "A1:A1", "values": [["x"]]},
    )

    assert response.status_code == 503
    assert store.list_pending_actions("order-6") == []
