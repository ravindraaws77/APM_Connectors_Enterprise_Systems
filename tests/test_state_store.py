from pathlib import Path

from apm_connectors.state.store import StateStore


def test_status_roundtrip(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    assert store.get_status("order-1") is None

    store.set_status("order-1", stage="order_received")
    status = store.get_status("order-1")
    assert status["stage"] == "order_received"
    assert "created_at" in status

    store.set_status("order-1", stage="delivered")
    assert store.get_status("order-1")["stage"] == "delivered"

    processes = store.list_processes()
    assert len(processes) == 1
    assert processes[0]["process_id"] == "order-1"


def test_audit_log(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    store.log_event("order-1", "gmail", "read", "Checked inbox for order-1")
    store.log_event("order-1", "gmail", "read", "Checked inbox again")
    store.log_event("order-2", "calendar", "read", "Checked calendar for order-2")

    all_events = store.list_events()
    assert len(all_events) == 3

    order_1_events = store.list_events(process_id="order-1")
    assert len(order_1_events) == 2

    limited = store.list_events(limit=1)
    assert len(limited) == 1


def test_pending_action_approval_flow(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    action = store.add_pending_action(
        process_id="order-1",
        tool="gmail",
        description="Send a follow-up email about the delayed shipment",
        payload={"to": "customer@example.com"},
    )
    assert action["status"] == "pending"
    assert len(store.list_pending_actions()) == 1

    resolved = store.resolve_pending_action(action["id"], approved=True)
    assert resolved["status"] == "approved"
    assert len(store.list_pending_actions()) == 0

    events = store.list_events(process_id="order-1")
    event_types = [e["event_type"] for e in events]
    assert "action_proposed" in event_types
    assert "action_approved" in event_types


def test_pending_action_rejection(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    action = store.add_pending_action(
        process_id="order-1",
        tool="calendar",
        description="Create a reminder event",
        payload={},
    )
    resolved = store.resolve_pending_action(action["id"], approved=False)
    assert resolved["status"] == "rejected"
    assert len(store.list_pending_actions()) == 0


def test_resolve_unknown_action_returns_none(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    assert store.resolve_pending_action("does-not-exist", approved=True) is None


def test_pending_action_category_defaults_to_other(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    action = store.add_pending_action(
        process_id="order-1", tool="gmail", description="x", payload={}
    )

    assert action["category"] == "other"


def test_pending_action_category_is_stored_and_logged(tmp_path: Path) -> None:
    """Category flows through to both the pending-action record and every
    audit event logged for it (proposed and, here, approved) -- this is
    what lets the History table color-code by category to surface a
    recurring pattern across processes.
    """
    store = StateStore(tmp_path / "state.json")

    action = store.add_pending_action(
        process_id="order-1",
        tool="gmail",
        description="Send a follow-up email about the delayed shipment",
        payload={"to": "customer@realcorp.io"},
        category="shipment_delay",
    )
    assert action["category"] == "shipment_delay"

    store.resolve_pending_action(action["id"], approved=True)

    events = store.list_events(process_id="order-1")
    proposed_event = next(e for e in events if e["event_type"] == "action_proposed")
    approved_event = next(e for e in events if e["event_type"] == "action_approved")
    assert proposed_event["details"]["category"] == "shipment_delay"
    assert approved_event["details"]["category"] == "shipment_delay"
