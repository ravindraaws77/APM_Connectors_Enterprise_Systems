"""Tests that the action graph (tests/test_action_graph.py) behaves the
same way with a real Postgres checkpointer as it does with MemorySaver,
plus the one thing MemorySaver structurally cannot cover: that a paused
(proposed-but-not-yet-approved) process survives a restart -- a fresh
checkpointer/graph, standing in for a redeployed API process, resuming a
process an earlier instance started.

Requires the optional `postgres` extra and a real, reachable Postgres:
skipped entirely if `psycopg`/`langgraph.checkpoint.postgres` isn't
installed, and skipped with a clear reason if `APM_TEST_DATABASE_URL`
isn't set -- see docs/running-locally.md.
"""

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("langgraph.checkpoint.postgres")

from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402

from apm_connectors.graph import build_action_graph, resume_process, start_action  # noqa: E402
from apm_connectors.state.postgres_store import PostgresStateStore  # noqa: E402
from apm_connectors.tools.calendar_tool import CalendarTool  # noqa: E402
from apm_connectors.tools.gmail_tool import GmailTool  # noqa: E402
from tests.test_calendar_tool import FakeCalendarClient  # noqa: E402
from tests.test_gmail_tool import FakeGmailClient  # noqa: E402

TEST_DATABASE_URL = os.environ.get("APM_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="set APM_TEST_DATABASE_URL to a Postgres connection string to run these tests",
)


def _pool() -> ConnectionPool:
    return ConnectionPool(
        TEST_DATABASE_URL,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        open=True,
    )


def _build(pool: ConnectionPool):
    store = PostgresStateStore(pool)
    gmail_client = FakeGmailClient([])
    gmail_tool = GmailTool(store, gmail_client)
    calendar_client = FakeCalendarClient([])
    calendar_tool = CalendarTool(store, calendar_client)

    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    graph = build_action_graph(tools, store, checkpointer=checkpointer)
    return graph, store, gmail_client, calendar_client


@pytest.fixture
def pool():
    p = _pool()
    # PostgresStateStore.__init__ creates apm_processes/apm_events/
    # apm_pending_actions if they don't exist yet (idempotent) -- needed
    # here because this fixture runs first on a brand-new test database,
    # before anything else has had a chance to create them, and TRUNCATE
    # below fails on a table that was never created.
    PostgresStateStore(p)
    with p.connection() as conn:
        conn.execute("TRUNCATE apm_processes, apm_events, apm_pending_actions")
        conn.execute(
            "DROP TABLE IF EXISTS checkpoints, checkpoint_blobs, checkpoint_writes, "
            "checkpoint_migrations CASCADE"
        )
    yield p
    p.close()


def test_approval_executes_the_action(pool: ConnectionPool, tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(pool)
    start_action(
        graph,
        "order-1",
        tool="gmail",
        method="send_email",
        description="Send a follow-up email",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )

    outcome = resume_process(graph, "order-1", approved=True)

    assert outcome.pending_action is None
    assert outcome.final_result["executed"] is True
    assert len(gmail_client.sent) == 1
    assert store.list_pending_actions("order-1") == []


def test_rejection_does_not_execute(pool: ConnectionPool, tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(pool)
    start_action(
        graph,
        "order-1",
        tool="gmail",
        method="send_email",
        description="Send a follow-up email",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )

    outcome = resume_process(graph, "order-1", approved=False)

    assert outcome.final_result == {"executed": False, "reason": "rejected"}
    assert gmail_client.sent == []


def test_paused_process_survives_a_restart(pool: ConnectionPool, tmp_path: Path) -> None:
    """The scenario MemorySaver can't offer: propose an action, throw
    away every in-process object (graph, checkpointer, store, tools --
    standing in for a redeployed/restarted API server), rebuild them
    fresh from the same DATABASE_URL, and confirm the paused process is
    still there and resumable.
    """
    graph, store, gmail_client, _ = _build(pool)
    outcome = start_action(
        graph,
        "order-7",
        tool="gmail",
        method="send_email",
        description="Notify customer of delay",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Delayed."},
    )
    assert outcome.pending_action is not None
    del graph, store, gmail_client

    fresh_graph, fresh_store, fresh_gmail_client, _ = _build(pool)
    assert len(fresh_store.list_pending_actions("order-7")) == 1

    resumed = resume_process(fresh_graph, "order-7", approved=True)

    assert resumed.final_result["executed"] is True
    assert len(fresh_gmail_client.sent) == 1
    assert fresh_store.list_pending_actions("order-7") == []
