"""Tests for build_action_graph/start_action — the propose -> approval ->
execute graph a caller (an external reasoning layer, standing in for a
future voice/LiveKit component) drives directly, with no fetch/reason
step and no reasoner/Anthropic dependency. Same non-negotiable rule as
build_graph (tests/test_agent_graph.py): a proposed write must not
execute until a human decision arrives via resume_process.
"""

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from apm_connectors.graph import build_action_graph, resume_process, start_action
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_gmail_tool import FakeGmailClient


def _build(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient([])
    gmail_tool = GmailTool(store, gmail_client)
    calendar_client = FakeCalendarClient([])
    calendar_tool = CalendarTool(store, calendar_client)

    tools = {"gmail": gmail_tool, "google_calendar": calendar_tool}
    graph = build_action_graph(tools, store, checkpointer=MemorySaver())
    return graph, store, gmail_client, calendar_client


def test_start_action_always_pauses_for_approval(tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(tmp_path)

    outcome = start_action(
        graph,
        "order-1",
        tool="gmail",
        method="send_email",
        description="Send a follow-up email",
        payload={"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."},
    )

    assert outcome.final_result is None
    assert outcome.pending_action is not None
    assert outcome.pending_action["tool"] == "gmail"
    assert outcome.pending_action["method"] == "send_email"

    # Nothing has actually happened yet.
    assert gmail_client.sent == []
    assert len(store.list_pending_actions("order-1")) == 1


def test_approval_executes_the_action(tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(tmp_path)
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
    assert outcome.final_result is not None
    assert outcome.final_result["executed"] is True
    assert len(gmail_client.sent) == 1
    assert gmail_client.sent[0]["to"] == "customer@realcorp.io"
    assert store.list_pending_actions("order-1") == []


def test_rejection_does_not_execute(tmp_path: Path) -> None:
    graph, store, gmail_client, _ = _build(tmp_path)
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
    assert store.list_pending_actions("order-1") == []


def test_calendar_action_via_the_same_graph(tmp_path: Path) -> None:
    """A second tool through the same graph instance, to confirm nothing
    about propose/approval/execute is Gmail-specific.
    """
    graph, store, _, calendar_client = _build(tmp_path)
    start_action(
        graph,
        "order-2",
        tool="google_calendar",
        method="create_event",
        description="Create a renewal reminder",
        payload={"title": "Renewal call", "start": "2026-09-10T15:00:00Z", "end": "2026-09-10T15:30:00Z"},
    )

    outcome = resume_process(graph, "order-2", approved=True)

    assert outcome.final_result["executed"] is True
    assert len(calendar_client.inserted) == 1
