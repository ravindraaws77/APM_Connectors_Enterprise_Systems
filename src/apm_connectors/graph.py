"""A small LangGraph process (propose -> human-approval interrupt ->
execute -> persist) that gates every write this package's connectors
make, and the audit trail alongside it. This is *not* a reasoning
engine or an orchestrator/supervisor — it accepts a tool/method/payload
a caller has already decided on and does exactly two things: (1) makes
that write physically impossible to execute without an explicit human
decision, and (2) records the read/proposed/approved/rejected/executed/
failed trail for it. Reasoning, intent parsing, and routing between
multiple specialized agents are a separate layer's job, deployed
separately, calling this package's API (see docs/api-contract.md).

Usage (see scripts/api_smoke_test.py / tests/test_action_graph.py):

    graph = build_action_graph(tools, state_store, checkpointer)
    result = start_action(graph, process_id, tool="gmail", method="send_email",
                           description="...", payload={...})
    if result.pending_action:
        ...show it to a human, get a decision...
        result = resume_process(graph, process_id, approved=True)
    print(result.final_result)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from apm_connectors.state.store import StateStore
from apm_connectors.tools.base import BaseTool


class GraphState(TypedDict, total=False):
    process_id: str
    category: str
    proposed_action: dict[str, Any] | None
    pending_action_id: str | None
    decision: bool | None
    result: dict[str, Any] | None


@dataclass(frozen=True)
class RunOutcome:
    """What start_action/resume_process hand back to the caller: either
    the graph is paused waiting for a human decision (pending_action
    set), or it has finished (final_result set).
    """

    process_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None


def _config(process_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": process_id}}


def _propose_node(state_store: StateStore):
    def propose_node(state: GraphState) -> dict[str, Any]:
        """Records the pending action exactly once. Deliberately kept
        separate from approval_node: this node runs to completion
        without ever calling interrupt(), so — unlike approval_node — it
        is never replayed, and add_pending_action never double-fires.
        """
        process_id = state["process_id"]
        proposed = state.get("proposed_action")
        if not proposed:
            return {"pending_action_id": None}

        action_record = state_store.add_pending_action(
            process_id=process_id,
            tool=proposed["tool"],
            description=proposed["description"],
            payload=proposed,
            category=state.get("category", "other"),
        )
        return {"pending_action_id": action_record["id"]}

    return propose_node


def _approval_node(state_store: StateStore):
    def approval_node(state: GraphState) -> dict[str, Any]:
        """The non-negotiable gate: execution physically cannot continue
        past interrupt() without a human decision arriving via
        Command(resume=...) — see resume_process below.

        On resume, LangGraph re-runs this node function from the top;
        interrupt() is the first (and only) side-effecting statement here
        so that replay is harmless — everything above it is a plain read
        of already-checkpointed state, and everything below it (recording
        the decision) executes exactly once, on the resume pass.
        """
        proposed = state.get("proposed_action")
        action_id = state.get("pending_action_id")
        if not proposed or not action_id:
            return {"decision": None}

        decision = interrupt(
            {
                "type": "approval_request",
                "action_id": action_id,
                "tool": proposed["tool"],
                "method": proposed["method"],
                "description": proposed["description"],
                "payload": proposed["payload"],
                "category": state.get("category", "other"),
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        state_store.resolve_pending_action(action_id, approved=approved)
        return {"decision": approved}

    return approval_node


def _execute_node(tools: dict[str, BaseTool], state_store: StateStore):
    def execute_node(state: GraphState) -> dict[str, Any]:
        process_id = state["process_id"]
        proposed = state.get("proposed_action")
        decision = state.get("decision")

        if not proposed or not decision:
            outcome = {"executed": False, "reason": "no_action_proposed" if not proposed else "rejected"}
            state_store.set_status(process_id, stage="done", result=outcome)
            return {"result": outcome}

        tool = tools[proposed["tool"]]
        method = getattr(tool, proposed["method"])
        action_result = method(process_id, dry_run=False, **proposed["payload"])
        outcome = {
            "executed": action_result.executed,
            "description": action_result.description,
            "details": action_result.details,
        }
        state_store.set_status(process_id, stage="done", result=outcome)
        return {"result": outcome}

    return execute_node


def build_action_graph(tools: dict[str, BaseTool], state_store: StateStore, checkpointer: Any):
    """`tools` keys are tool names ("gmail", "google_calendar", "ms_excel",
    "excel_file"); execute_node looks up whichever one a proposed action
    names. `checkpointer` is required explicitly (rather than defaulting
    to MemorySaver here) so callers decide the persistence story.
    """
    graph = StateGraph(GraphState)
    graph.add_node("propose", _propose_node(state_store))
    graph.add_node("approval", _approval_node(state_store))
    graph.add_node("execute", _execute_node(tools, state_store))

    graph.set_entry_point("propose")
    graph.add_edge("propose", "approval")
    graph.add_edge("approval", "execute")
    graph.add_edge("execute", END)

    return graph.compile(checkpointer=checkpointer)


def start_action(
    graph: Any,
    process_id: str,
    tool: str,
    method: str,
    description: str,
    payload: dict[str, Any],
    category: str = "manual",
) -> RunOutcome:
    """Run the propose -> approval -> execute graph for a tool action a
    caller (a reasoning/orchestration layer, a script, a test) has
    already decided on. Always returns a paused RunOutcome
    (pending_action set) — the caller only calls this when it does want
    an action taken. Resume with resume_process(graph, process_id,
    approved=...), passing this same graph.
    """
    proposed_action = {"tool": tool, "method": method, "description": description, "payload": payload}
    initial_state: GraphState = {"process_id": process_id, "proposed_action": proposed_action, "category": category}
    result = graph.invoke(initial_state, config=_config(process_id))
    return _to_outcome(process_id, result)


def resume_process(graph: Any, process_id: str, approved: bool) -> RunOutcome:
    """Resume a paused graph with a human's Approve/Reject decision."""
    result = graph.invoke(Command(resume={"approved": approved}), config=_config(process_id))
    return _to_outcome(process_id, result)


def _to_outcome(process_id: str, result: dict[str, Any]) -> RunOutcome:
    if "__interrupt__" in result:
        return RunOutcome(
            process_id=process_id,
            summary=result.get("summary"),
            pending_action=result["__interrupt__"][0].value,
            final_result=None,
        )
    return RunOutcome(
        process_id=process_id,
        summary=result.get("summary"),
        pending_action=None,
        final_result=result.get("result"),
    )
