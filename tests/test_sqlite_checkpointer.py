"""Tests that the action graph (tests/test_action_graph.py) behaves the
same way with a real SqliteSaver checkpointer as it does with MemorySaver,
plus the one thing MemorySaver structurally cannot cover: that a paused
(proposed-but-not-yet-approved) process survives a restart -- a fresh
checkpointer/graph, standing in for a restarted API process, resuming a
process an earlier instance started. This is the default (no
DATABASE_URL) checkpointer -- see api/dependencies.py's get_action_graph
and its _get_sqlite_connection helper.
"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from apm_connectors.graph import build_action_graph, resume_process, start_action
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_gmail_tool import FakeGmailClient


def _build(tmp_path: Path, conn: sqlite3.Connection):
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    gmail_tool = GmailTool(store, gmail_client)
    calendar_client = FakeCalendarClient([])
    calendar_tool = CalendarTool(store, calendar_client)

    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    graph = build_action_graph(tools, store, checkpointer=checkpointer)
    return graph, store, gmail_client, calendar_client


def test_approval_executes_the_action(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "checkpoints.sqlite"), check_same_thread=False)
    graph, store, gmail_client, _ = _build(tmp_path, conn)
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


def test_rejection_does_not_execute(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "checkpoints.sqlite"), check_same_thread=False)
    graph, store, gmail_client, _ = _build(tmp_path, conn)
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


def test_paused_process_survives_a_restart(tmp_path: Path) -> None:
    """The scenario MemorySaver can't offer: propose an action, throw
    away every in-process object (graph, checkpointer, tools -- standing
    in for a restarted API process), reopen the same SQLite file fresh,
    and confirm the paused process is still there and resumable. The
    state store itself (a separate JSON file) is rebuilt fresh too, to
    confirm it agrees with the checkpointer about what's still pending.
    """
    db_path = tmp_path / "checkpoints.sqlite"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    graph, store, gmail_client, _ = _build(tmp_path, conn)
    outcome = start_action(
        graph,
        "order-7",
        tool="gmail",
        method="send_email",
        description="Notify customer of delay",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Delayed."},
    )
    assert outcome.pending_action is not None
    conn.close()
    del graph, store, gmail_client, conn

    fresh_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    fresh_graph, fresh_store, fresh_gmail_client, _ = _build(tmp_path, fresh_conn)
    assert len(fresh_store.list_pending_actions("order-7")) == 1

    resumed = resume_process(fresh_graph, "order-7", approved=True)

    assert resumed.final_result["executed"] is True
    assert len(fresh_gmail_client.sent) == 1
    assert fresh_store.list_pending_actions("order-7") == []
