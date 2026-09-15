"""Tests for the /tools/* routes (apm_connectors.api.tools_routes) — the direct
per-tool read/write API, with no reasoning involved. Uses the real tools
wired to fake clients (same fixtures as tests/test_api.py), injected via
FastAPI's dependency_overrides, so no live credentials are needed.

Covers: reads return data immediately; a write pauses for approval and
does not execute until POST /tools/actions/{action_id}/decision
approves it; rejecting doesn't execute; a tool that isn't configured on
this server returns a clean 503 rather than a crash; process_id is
optional everywhere -- omitting it still works, with the server
generating an id used for audit logging (reads) or handed back as
action_id (writes).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from apm_connectors.graph import build_action_graph
from apm_connectors.api.app import create_app
from apm_connectors.api import dependencies as dependencies_module
from apm_connectors.api.dependencies import get_action_graph, get_tools, require_caller
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.drive_tool import DriveTool
from apm_connectors.tools.excel_file_tool import ExcelFileTool
from apm_connectors.tools.gmail_tool import GmailTool
from apm_connectors.tools.jira_tool import JiraTool
from apm_connectors.tools.salesforce_tool import SalesforceTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_drive_tool import FOLDER_ID, FakeDriveClient
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes
from tests.test_gmail_tool import FakeGmailClient, _raw_message
from tests.test_jira_tool import FakeJiraClient, _raw_issue
from tests.test_salesforce_tool import FakeSalesforceClient, _raw_record


def _client(
    tmp_path: Path,
    with_excel: bool = True,
    with_salesforce: bool = True,
    with_jira: bool = True,
    gmail_messages: list | None = None,
):
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
    salesforce_client = None
    if with_salesforce:
        salesforce_client = FakeSalesforceClient(
            [_raw_record("006abc", "Opportunity", Name="Acme Renewal", StageName="Negotiation")]
        )
        tools["salesforce"] = SalesforceTool(store, salesforce_client)
    jira_client = None
    if with_jira:
        jira_client = FakeJiraClient([_raw_issue("OPS-1", "Bug", summary="Payments failing")])
        tools["jira"] = JiraTool(store, jira_client)
    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_action_graph] = lambda: action_graph
    return TestClient(app), store, gmail_client, calendar_client, excel_source, salesforce_client, jira_client


# -- reads --------------------------------------------------------------


def test_gmail_search_returns_data_immediately(tmp_path: Path) -> None:
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    client, store, gmail_client, _, _, _, _ = _client(tmp_path, gmail_messages=[message])

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


def test_read_without_process_id_still_works_and_is_logged(tmp_path: Path) -> None:
    """process_id is optional -- a caller with no internal id of its own
    can just omit it. The server generates one internally so the read
    is still on the audit trail, just not grouped under a caller-chosen
    label.
    """
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    client, store, *_ = _client(tmp_path, gmail_messages=[message])

    response = client.post("/tools/gmail/search", json={"query": "newer_than:7d"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    all_events = store.list_events()
    assert any(e["event_type"] == "read" and e["tool"] == "gmail" for e in all_events)


# -- writes: propose -> approve/reject -----------------------------------


def test_gmail_send_pauses_for_approval_then_executes(tmp_path: Path) -> None:
    client, store, gmail_client, _, _, _, _ = _client(tmp_path)

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


def test_gmail_send_without_process_id_returns_a_generated_action_id(tmp_path: Path) -> None:
    """The common case for a calling agent with no APM-internal id: omit
    process_id entirely. The server generates one, returns it as
    action_id, and that's what resolves the decision.
    """
    client, store, gmail_client, _, _, _, _ = _client(tmp_path)

    propose = client.post(
        "/tools/gmail/send",
        json={"to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
    )
    assert propose.status_code == 200
    action_id = propose.json()["action_id"]
    assert action_id  # server-generated, non-empty
    assert len(store.list_pending_actions(action_id)) == 1

    decide = client.post(f"/tools/actions/{action_id}/decision", json={"approved": True})

    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(gmail_client.sent) == 1


def test_gmail_send_rejected_does_not_execute(tmp_path: Path) -> None:
    client, store, gmail_client, _, _, _, _ = _client(tmp_path)
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
    client, store, _, calendar_client, _, _, _ = _client(tmp_path)

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
    client, store, _, _, excel_source, _, _ = _client(tmp_path)

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


# -- Salesforce -----------------------------------------------------------


def test_salesforce_query_returns_data_immediately(tmp_path: Path) -> None:
    client, store, *_ = _client(tmp_path)

    response = client.post(
        "/tools/salesforce/query",
        json={"process_id": "order-7", "soql": "SELECT Id, Name FROM Opportunity"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["record_id"] == "006abc"
    assert any(e["event_type"] == "read" and e["tool"] == "salesforce" for e in store.list_events("order-7"))


def test_salesforce_read(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path)

    response = client.post(
        "/tools/salesforce/read",
        json={"object_name": "Opportunity", "record_id": "006abc"},
    )

    assert response.status_code == 200
    assert response.json()["record_id"] == "006abc"


def test_salesforce_unconfigured_returns_503(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, with_salesforce=False)

    response = client.post("/tools/salesforce/query", json={"soql": "SELECT Id FROM Opportunity"})

    assert response.status_code == 503


def test_salesforce_create_gated(tmp_path: Path) -> None:
    client, store, _, _, _, salesforce_client, _ = _client(tmp_path)

    propose = client.post(
        "/tools/salesforce/create",
        json={"process_id": "order-8", "object_name": "Lead", "fields": {"LastName": "Doe", "Company": "Acme"}},
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["tool"] == "salesforce"
    assert salesforce_client.created == []

    decide = client.post("/tools/actions/order-8/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(salesforce_client.created) == 1


def test_salesforce_update_gated(tmp_path: Path) -> None:
    client, store, _, _, _, salesforce_client, _ = _client(tmp_path)

    propose = client.post(
        "/tools/salesforce/update",
        json={
            "process_id": "order-9",
            "object_name": "Opportunity",
            "record_id": "006abc",
            "fields": {"StageName": "Closed Won"},
        },
    )
    assert propose.status_code == 200
    assert salesforce_client.updated == []

    decide = client.post("/tools/actions/order-9/decision", json={"approved": False})
    assert decide.status_code == 200
    assert decide.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert salesforce_client.updated == []


# -- Jira -------------------------------------------------------------------


def test_jira_search_returns_data_immediately(tmp_path: Path) -> None:
    client, store, *_ = _client(tmp_path)

    response = client.post(
        "/tools/jira/search",
        json={"process_id": "order-10", "jql": "project = OPS"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["issue_key"] == "OPS-1"
    assert any(e["event_type"] == "read" and e["tool"] == "jira" for e in store.list_events("order-10"))


def test_jira_read(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path)

    response = client.post("/tools/jira/read", json={"issue_key": "OPS-1"})

    assert response.status_code == 200
    assert response.json()["issue_key"] == "OPS-1"


def test_jira_unconfigured_returns_503(tmp_path: Path) -> None:
    client, *_ = _client(tmp_path, with_jira=False)

    response = client.post("/tools/jira/search", json={"jql": "project = OPS"})

    assert response.status_code == 503


def test_jira_create_gated(tmp_path: Path) -> None:
    client, store, _, _, _, _, jira_client = _client(tmp_path)

    propose = client.post(
        "/tools/jira/create",
        json={
            "process_id": "order-11",
            "fields": {"project": {"key": "OPS"}, "summary": "Fix the thing", "issuetype": {"name": "Bug"}},
        },
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["tool"] == "jira"
    assert jira_client.created == []

    decide = client.post("/tools/actions/order-11/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(jira_client.created) == 1


def test_jira_update_gated(tmp_path: Path) -> None:
    client, store, _, _, _, _, jira_client = _client(tmp_path)

    propose = client.post(
        "/tools/jira/update",
        json={"process_id": "order-12", "issue_key": "OPS-1", "fields": {"summary": "Updated title"}},
    )
    assert propose.status_code == 200
    assert jira_client.updated == []

    decide = client.post("/tools/actions/order-12/decision", json={"approved": False})
    assert decide.status_code == 200
    assert decide.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert jira_client.updated == []


# -- Drive documents --------------------------------------------------------
# A dedicated helper (not _client above) since Drive is a single optional
# tool, not part of the fixed 7-tuple every other test unpacks.


def _drive_client(tmp_path: Path, with_drive: bool = True):
    store = StateStore(tmp_path / "state.json")
    tools: dict = {}
    drive_client = None
    if with_drive:
        drive_client = FakeDriveClient()
        drive_client.add_file("f1", "Contract.pdf", "application/pdf", [FOLDER_ID], b"pdf-bytes")
        tools["drive"] = DriveTool(store, drive_client, folder_id=FOLDER_ID)
    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_action_graph] = lambda: action_graph
    return TestClient(app), store, drive_client


def test_drive_list_returns_data_immediately(tmp_path: Path) -> None:
    client, store, _ = _drive_client(tmp_path)

    response = client.post("/tools/drive/list", json={"process_id": "order-13"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Contract.pdf"
    assert any(e["event_type"] == "read" for e in store.list_events("order-13"))


def test_drive_read_returns_base64_content(tmp_path: Path) -> None:
    client, *_ = _drive_client(tmp_path)

    response = client.post("/tools/drive/read", json={"process_id": "order-13", "file_id": "f1"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Contract.pdf"
    assert body["size"] == len(b"pdf-bytes")


def test_drive_upload_gated(tmp_path: Path) -> None:
    client, store, drive_client = _drive_client(tmp_path)

    propose = client.post(
        "/tools/drive/upload",
        json={
            "process_id": "order-14",
            "name": "Renewal.pdf",
            "content_base64": "bmV3LWRvYw==",
            "mime_type": "application/pdf",
        },
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["tool"] == "drive"
    assert drive_client.upload_count == 0

    decide = client.post("/tools/actions/order-14/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert drive_client.upload_count == 1


def test_drive_update_gated_and_rejected_does_not_execute(tmp_path: Path) -> None:
    client, store, drive_client = _drive_client(tmp_path)

    propose = client.post(
        "/tools/drive/update",
        json={"process_id": "order-15", "file_id": "f1", "content_base64": "bmV3LWJ5dGVz"},
    )
    assert propose.status_code == 200
    assert drive_client.update_count == 0

    decide = client.post("/tools/actions/order-15/decision", json={"approved": False})
    assert decide.status_code == 200
    assert decide.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert drive_client.update_count == 0


def test_drive_read_unconfigured_returns_503(tmp_path: Path) -> None:
    client, *_ = _drive_client(tmp_path, with_drive=False)

    response = client.post("/tools/drive/read", json={"process_id": "order-16", "file_id": "f1"})

    assert response.status_code == 503


# -- Auth (require_caller) ---------------------------------------------------
# By default (no APM_API_KEYS, and _client doesn't override require_caller)
# every test above already exercises "auth disabled" -- every route reachable
# with no Authorization header at all. These tests exercise the gate itself:
# 401s once configured, and proposed_by/decided_by attribution once a caller
# is known.


def test_routes_reachable_with_no_auth_configured(tmp_path: Path) -> None:
    """Sanity check for the whole suite above: with no APM_API_KEYS, a
    request with no Authorization header at all still succeeds -- the
    documented local-dev default, unchanged by adding auth support.
    """
    client, *_ = _client(tmp_path, with_excel=False)
    response = client.post("/tools/gmail/search", json={"query": "x"})
    assert response.status_code == 200


def test_read_route_401s_with_no_token_once_api_keys_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})
    client, *_ = _client(tmp_path, with_excel=False)

    response = client.post("/tools/gmail/search", json={"query": "x"})

    assert response.status_code == 401


def test_read_route_401s_with_wrong_token_once_api_keys_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})
    client, *_ = _client(tmp_path, with_excel=False)

    response = client.post(
        "/tools/gmail/search", json={"query": "x"}, headers={"Authorization": "Bearer wrong-token"}
    )

    assert response.status_code == 401


def test_read_route_succeeds_with_valid_token_once_api_keys_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    client, *_ = _client(tmp_path, gmail_messages=[message])

    response = client.post(
        "/tools/gmail/search", json={"query": "x"}, headers={"Authorization": "Bearer sk_abc123"}
    )

    assert response.status_code == 200


def test_processes_routes_gated_but_health_is_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})
    client, *_ = _client(tmp_path)

    assert client.get("/health").status_code == 200
    assert client.get("/processes").status_code == 401
    assert client.get("/processes", headers={"Authorization": "Bearer sk_abc123"}).status_code == 200


def test_propose_and_decide_attribute_different_authenticated_callers(tmp_path: Path) -> None:
    """gmail_send records proposed_by from whoever's authenticated on
    the propose call; decide_action records decided_by from whoever's
    authenticated on the decision call -- independent identities, since
    a different person can review a proposal than the one (service or
    human) that raised it.
    """
    client, store, gmail_client, *_ = _client(tmp_path)
    app = client.app
    current_caller = {"name": "orchestrator-service"}
    app.dependency_overrides[require_caller] = lambda: current_caller["name"]

    propose = client.post(
        "/tools/gmail/send",
        json={"process_id": "order-20", "to": "customer@realcorp.io", "subject": "Update", "body": "..."},
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["proposed_by"] == "orchestrator-service"

    current_caller["name"] = "alice"
    decide = client.post("/tools/actions/order-20/decision", json={"approved": True})
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True

    events = store.list_events("order-20")
    proposed_event = next(e for e in events if e["event_type"] == "action_proposed")
    approved_event = next(e for e in events if e["event_type"] == "action_approved")
    assert proposed_event["caller"] == "orchestrator-service"
    assert approved_event["caller"] == "alice"


def test_read_routes_attribute_the_authenticated_caller(tmp_path: Path) -> None:
    """Not just proposed_by/decided_by on writes -- a plain read (any
    tool, gmail_search here) is attributed too once a caller is known,
    end to end through the route into the state store.
    """
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    client, store, *_ = _client(tmp_path, gmail_messages=[message])
    client.app.dependency_overrides[require_caller] = lambda: "alice"

    response = client.post("/tools/gmail/search", json={"process_id": "order-21", "query": "x"})

    assert response.status_code == 200
    events = [e for e in store.list_events("order-21") if e["event_type"] == "read"]
    assert len(events) == 1
    assert events[0]["caller"] == "alice"
