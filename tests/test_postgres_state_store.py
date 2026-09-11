"""Tests for PostgresStateStore -- same behavior contract as
tests/test_state_store.py's coverage of the file-backed StateStore (see
apm_connectors.state.store's module docstring on why the two must agree),
run against a real Postgres instead of a fake/mocked one.

Requires the optional `postgres` extra and a real, reachable Postgres:
skipped entirely if `psycopg` isn't installed, and skipped with a clear
reason if `APM_TEST_DATABASE_URL` isn't set -- see docs/running-locally.md.
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402

from apm_connectors.state.postgres_store import PostgresStateStore  # noqa: E402

TEST_DATABASE_URL = os.environ.get("APM_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="set APM_TEST_DATABASE_URL to a Postgres connection string to run these tests",
)


@pytest.fixture
def store():
    pool = ConnectionPool(
        TEST_DATABASE_URL,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        open=True,
    )
    s = PostgresStateStore(pool)
    with pool.connection() as conn:
        conn.execute("TRUNCATE apm_processes, apm_events, apm_pending_actions")
    yield s
    pool.close()


def test_status_roundtrip(store: PostgresStateStore) -> None:
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


def test_audit_log(store: PostgresStateStore) -> None:
    store.log_event("order-1", "gmail", "read", "Checked inbox for order-1")
    store.log_event("order-1", "gmail", "read", "Checked inbox again")
    store.log_event("order-2", "calendar", "read", "Checked calendar for order-2")

    all_events = store.list_events()
    assert len(all_events) == 3

    order_1_events = store.list_events(process_id="order-1")
    assert len(order_1_events) == 2

    limited = store.list_events(limit=1)
    assert len(limited) == 1


def test_pending_action_approval_flow(store: PostgresStateStore) -> None:
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


def test_pending_action_rejection(store: PostgresStateStore) -> None:
    action = store.add_pending_action(
        process_id="order-1",
        tool="calendar",
        description="Create a reminder event",
        payload={},
    )
    resolved = store.resolve_pending_action(action["id"], approved=False)
    assert resolved["status"] == "rejected"
    assert len(store.list_pending_actions()) == 0


def test_resolve_unknown_action_returns_none(store: PostgresStateStore) -> None:
    assert store.resolve_pending_action("does-not-exist", approved=True) is None


def test_pending_action_category_is_stored_and_logged(store: PostgresStateStore) -> None:
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


def test_state_survives_a_fresh_store_instance(store: PostgresStateStore) -> None:
    """The whole point of swapping in Postgres: a new process (a fresh
    PostgresStateStore, standing in for a redeployed/restarted API
    process) sees state a previous instance wrote.
    """
    store.set_status("order-9", stage="delivered")
    store.log_event("order-9", "gmail", "read", "Checked inbox")

    pool2 = ConnectionPool(
        TEST_DATABASE_URL,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        open=True,
    )
    try:
        fresh_store = PostgresStateStore(pool2)
        assert fresh_store.get_status("order-9")["stage"] == "delivered"
        assert len(fresh_store.list_events("order-9")) == 1
    finally:
        pool2.close()
