"""Direct per-tool read/write routes over the connector layer
(apm_connectors.tools) — no reasoning here. A caller (a reasoning/
orchestration layer deployed separately, a script, a test) decides
exactly what to read or what write to propose; this module never
guesses on the caller's behalf.

Reads execute immediately and return the tool's data straight back —
read is always allowed. Every write still goes through the same
non-negotiable human-approval gate: it calls start_action
(apm_connectors.graph.build_action_graph) to record a pending action
and pause, never the tool's write method directly. Approve/reject via
POST /tools/actions/{process_id}/decision.

See docs/api-contract.md for the full HTTP contract this router
implements — not meant to be reachable by an outside customer directly,
just the surface an internal reasoning/orchestration component calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apm_connectors.api._responses import to_response, upstream_error
from apm_connectors.api.dependencies import get_action_graph, get_tools
from apm_connectors.api.schemas import (
    CalendarCreateEventRequest,
    CalendarReadRequest,
    CalendarSearchRequest,
    DecisionRequest,
    ExcelReadRequest,
    ExcelWorksheetsRequest,
    ExcelWriteRequest,
    GmailReadRequest,
    GmailSearchRequest,
    GmailSendRequest,
    RunOutcomeResponse,
)
from apm_connectors.graph import resume_process, start_action
from apm_connectors.tools.base import BaseTool

router = APIRouter(prefix="/tools", tags=["tools"])


def _tool(tools: dict[str, BaseTool], name: str) -> BaseTool:
    if name not in tools:
        raise HTTPException(status_code=503, detail=f"tool not configured on this server: {name}")
    return tools[name]


def _propose(graph, process_id: str, tool: str, method: str, description: str, payload: dict) -> RunOutcomeResponse:
    try:
        outcome = start_action(graph, process_id, tool=tool, method=method, description=description, payload=payload)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return to_response(outcome)


# -- Gmail ----------------------------------------------------------------


@router.post("/gmail/search")
def gmail_search(body: GmailSearchRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:
    tool = _tool(tools, "gmail")
    try:
        results = tool.search_emails(body.process_id, query=body.query, max_results=body.max_results)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/gmail/read")
def gmail_read(body: GmailReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "gmail")
    try:
        result = tool.read_message(body.process_id, message_id=body.message_id)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/gmail/send", response_model=RunOutcomeResponse)
def gmail_send(
    body: GmailSendRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "gmail")  # fail fast, before recording a pending action doomed to fail on approval
    description = f"Send email to {body.to}: {body.subject!r}"
    payload = {"to": body.to, "subject": body.subject, "body": body.body}
    return _propose(graph, body.process_id, "gmail", "send_email", description, payload)


# -- Calendar ---------------------------------------------------------------


@router.post("/calendar/search")
def calendar_search(body: CalendarSearchRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:
    tool = _tool(tools, "google_calendar")
    try:
        results = tool.search_events(
            body.process_id,
            query=body.query,
            time_min=body.time_min,
            time_max=body.time_max,
            max_results=body.max_results,
        )
    except Exception as exc:
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/calendar/read")
def calendar_read(body: CalendarReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "google_calendar")
    try:
        result = tool.read_event(body.process_id, event_id=body.event_id)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/calendar/create-event", response_model=RunOutcomeResponse)
def calendar_create_event(
    body: CalendarCreateEventRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "google_calendar")
    description = f"Create Calendar event '{body.title}' at {body.start}"
    payload = {
        "title": body.title,
        "start": body.start,
        "end": body.end,
        "attendees": body.attendees,
        "location": body.location,
    }
    return _propose(graph, body.process_id, "google_calendar", "create_event", description, payload)


# -- Excel --------------------------------------------------------------


@router.post("/excel/worksheets")
def excel_worksheets(body: ExcelWorksheetsRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[str]:
    tool = _tool(tools, "excel_file")
    try:
        return tool.list_worksheets(body.process_id)
    except Exception as exc:
        raise upstream_error(exc) from exc


@router.post("/excel/read")
def excel_read(body: ExcelReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "excel_file")
    try:
        result = tool.read_range(body.process_id, sheet_name=body.sheet_name, address=body.address)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/excel/write", response_model=RunOutcomeResponse)
def excel_write(
    body: ExcelWriteRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "excel_file")
    description = f"Write {len(body.values)} row(s) to {body.sheet_name}!{body.address}"
    payload = {"sheet_name": body.sheet_name, "address": body.address, "values": body.values}
    return _propose(graph, body.process_id, "excel_file", "write_range", description, payload)


# -- Shared decision route for every /tools/* write above -------------------


@router.post("/actions/{process_id}/decision", response_model=RunOutcomeResponse)
def decide_action(process_id: str, body: DecisionRequest, graph=Depends(get_action_graph)) -> RunOutcomeResponse:
    try:
        outcome = resume_process(graph, process_id, approved=body.approved)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return to_response(outcome)
