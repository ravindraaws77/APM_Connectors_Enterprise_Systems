"""End-to-end integration tests against a real running server process,
over real HTTP -- the propose -> approve -> execute contract every
external reasoning/orchestration layer relies on (docs/api-contract.md),
exercised the way an actual deployment would be hit, not via FastAPI's
in-process TestClient (see tests/test_tools_api.py for that version).

Every write here is a dry run in effect: the connectors underneath are
fakes (tests/test_*_tool.py's FakeGmailClient etc.), so nothing here
ever reaches a real Gmail/Calendar/Excel account, but the HTTP contract,
the approval gate, and the audit trail are exercised for real.
"""

from __future__ import annotations

import requests

from tests.integration.conftest import LiveServer


def test_health_and_processes_are_reachable(live_server: LiveServer) -> None:
    health = requests.get(f"{live_server.base_url}/health", timeout=5)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    processes = requests.get(f"{live_server.base_url}/processes", timeout=5)
    assert processes.status_code == 200
    assert isinstance(processes.json(), list)


def test_gmail_send_end_to_end_over_http(live_server: LiveServer) -> None:
    base = live_server.base_url

    propose = requests.post(
        f"{base}/tools/gmail/send",
        json={"process_id": "int-1", "to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
        timeout=5,
    )
    assert propose.status_code == 200
    body = propose.json()
    assert body["final_result"] is None
    assert body["pending_action"]["tool"] == "gmail"
    assert live_server.gmail_client.sent == []

    pending = requests.get(f"{base}/processes/int-1/pending", timeout=5)
    assert pending.status_code == 200
    assert len(pending.json()) == 1

    decide = requests.post(f"{base}/tools/actions/int-1/decision", json={"approved": True}, timeout=5)
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(live_server.gmail_client.sent) == 1

    history = requests.get(f"{base}/processes/int-1/history", timeout=5).json()
    event_types = {event["event_type"] for event in history}
    assert {"action_proposed", "action_approved", "action_executed"} <= event_types

    assert requests.get(f"{base}/processes/int-1/pending", timeout=5).json() == []


def test_gmail_send_without_process_id_returns_generated_action_id_over_http(live_server: LiveServer) -> None:
    base = live_server.base_url

    propose = requests.post(
        f"{base}/tools/gmail/send",
        json={"to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
        timeout=5,
    )
    assert propose.status_code == 200
    action_id = propose.json()["action_id"]
    assert action_id

    decide = requests.post(f"{base}/tools/actions/{action_id}/decision", json={"approved": True}, timeout=5)
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(live_server.gmail_client.sent) == 1


def test_gmail_send_rejected_over_http_does_not_execute(live_server: LiveServer) -> None:
    base = live_server.base_url
    requests.post(
        f"{base}/tools/gmail/send",
        json={"process_id": "int-2", "to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."},
        timeout=5,
    )

    decide = requests.post(f"{base}/tools/actions/int-2/decision", json={"approved": False}, timeout=5)

    assert decide.status_code == 200
    assert decide.json()["final_result"] == {"executed": False, "reason": "rejected"}
    assert live_server.gmail_client.sent == []
    assert requests.get(f"{base}/processes/int-2/pending", timeout=5).json() == []


def test_calendar_create_event_end_to_end_over_http(live_server: LiveServer) -> None:
    base = live_server.base_url

    propose = requests.post(
        f"{base}/tools/calendar/create-event",
        json={
            "process_id": "int-3",
            "title": "Renewal call",
            "start": "2026-09-10T15:00:00Z",
            "end": "2026-09-10T15:30:00Z",
        },
        timeout=5,
    )
    assert propose.status_code == 200
    assert live_server.calendar_client.inserted == []

    decide = requests.post(f"{base}/tools/actions/int-3/decision", json={"approved": True}, timeout=5)
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True
    assert len(live_server.calendar_client.inserted) == 1


def test_excel_write_end_to_end_over_http(live_server: LiveServer) -> None:
    base = live_server.base_url

    propose = requests.post(
        f"{base}/tools/excel/write",
        json={"process_id": "int-4", "sheet_name": "Renewals", "address": "A1:A1", "values": [["done"]]},
        timeout=5,
    )
    assert propose.status_code == 200
    assert propose.json()["pending_action"]["tool"] == "excel_file"

    decide = requests.post(f"{base}/tools/actions/int-4/decision", json={"approved": True}, timeout=5)
    assert decide.status_code == 200
    assert decide.json()["final_result"]["executed"] is True


def test_excel_worksheets_read_over_http(live_server: LiveServer) -> None:
    response = requests.post(
        f"{live_server.base_url}/tools/excel/worksheets", json={"process_id": "int-5"}, timeout=5
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


def test_unconfigured_tool_returns_503_over_http_without_creating_a_pending_action(
    live_server_factory,
) -> None:
    live_server = live_server_factory(with_excel=False)

    response = requests.post(
        f"{live_server.base_url}/tools/excel/write",
        json={"process_id": "int-6", "sheet_name": "Sheet1", "address": "A1:A1", "values": [["x"]]},
        timeout=5,
    )

    assert response.status_code == 503
    assert requests.get(f"{live_server.base_url}/processes/int-6/pending", timeout=5).json() == []


def test_unknown_process_status_is_a_clean_404_over_http(live_server: LiveServer) -> None:
    response = requests.get(f"{live_server.base_url}/processes/does-not-exist/status", timeout=5)
    assert response.status_code == 404
