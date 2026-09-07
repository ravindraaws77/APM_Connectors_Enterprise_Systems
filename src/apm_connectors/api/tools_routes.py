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
POST /tools/actions/{action_id}/decision.

process_id is optional on every route here (see schemas.py) -- a
caller with no internal process/case id of its own doesn't need to
invent one just to call a connector. _resolve_process_id generates one
when omitted, used only as the audit-trail grouping key for a read, or
as the action_id a write's response hands back for the decision call.

See docs/api-contract.md for the full HTTP contract this router
implements — not meant to be reachable by an outside customer directly,
just the surface an internal reasoning/orchestration component calls.
"""

from __future__ import annotations

import uuid

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
    JiraCreateRequest,
    JiraReadRequest,
    JiraSearchRequest,
    JiraUpdateRequest,
    RunOutcomeResponse,
    SalesforceCreateRequest,
    SalesforceQueryRequest,
    SalesforceReadRequest,
    SalesforceUpdateRequest,
)
from apm_connectors.graph import resume_process, start_action
from apm_connectors.tools.base import BaseTool

router = APIRouter(prefix="/tools", tags=["tools"])


def _tool(tools: dict[str, BaseTool], name: str) -> BaseTool:
    if name not in tools:
        raise HTTPException(status_code=503, detail=f"tool not configured on this server: {name}")
    return tools[name]


def _resolve_process_id(process_id: str | None) -> str:
    """Every call needs *some* id for the audit trail / action-graph
    thread key, but the caller doesn't have to supply one -- generate
    one when it's omitted. See this module's docstring and
    schemas.py's request-model comment.
    """
    return process_id or str(uuid.uuid4())


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
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_emails(process_id, query=body.query, max_results=body.max_results)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/gmail/read")
def gmail_read(body: GmailReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "gmail")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_message(process_id, message_id=body.message_id)
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
    action_id = _resolve_process_id(body.process_id)
    description = f"Send email to {body.to}: {body.subject!r}"
    payload = {"to": body.to, "subject": body.subject, "body": body.body}
    return _propose(graph, action_id, "gmail", "send_email", description, payload)


# -- Calendar ---------------------------------------------------------------


@router.post("/calendar/search")
def calendar_search(body: CalendarSearchRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:
    tool = _tool(tools, "google_calendar")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_events(
            process_id,
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
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_event(process_id, event_id=body.event_id)
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
    action_id = _resolve_process_id(body.process_id)
    description = f"Create Calendar event '{body.title}' at {body.start}"
    payload = {
        "title": body.title,
        "start": body.start,
        "end": body.end,
        "attendees": body.attendees,
        "location": body.location,
    }
    return _propose(graph, action_id, "google_calendar", "create_event", description, payload)


# -- Excel --------------------------------------------------------------


@router.post("/excel/worksheets")
def excel_worksheets(body: ExcelWorksheetsRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[str]:
    tool = _tool(tools, "excel_file")
    process_id = _resolve_process_id(body.process_id)
    try:
        return tool.list_worksheets(process_id)
    except Exception as exc:
        raise upstream_error(exc) from exc


@router.post("/excel/read")
def excel_read(body: ExcelReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "excel_file")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_range(process_id, sheet_name=body.sheet_name, address=body.address)
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
    action_id = _resolve_process_id(body.process_id)
    description = f"Write {len(body.values)} row(s) to {body.sheet_name}!{body.address}"
    payload = {"sheet_name": body.sheet_name, "address": body.address, "values": body.values}
    return _propose(graph, action_id, "excel_file", "write_range", description, payload)


# -- Salesforce ---------------------------------------------------------


@router.post("/salesforce/query")
def salesforce_query(body: SalesforceQueryRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:
    tool = _tool(tools, "salesforce")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.query_records(process_id, soql=body.soql)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/salesforce/read")
def salesforce_read(body: SalesforceReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "salesforce")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.get_record(process_id, object_name=body.object_name, record_id=body.record_id)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/salesforce/create", response_model=RunOutcomeResponse)
def salesforce_create(
    body: SalesforceCreateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "salesforce")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = f"Create Salesforce {body.object_name} record"
    payload = {"object_name": body.object_name, "fields": body.fields}
    return _propose(graph, action_id, "salesforce", "create_record", description, payload)


@router.post("/salesforce/update", response_model=RunOutcomeResponse)
def salesforce_update(
    body: SalesforceUpdateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "salesforce")
    action_id = _resolve_process_id(body.process_id)
    description = f"Update Salesforce {body.object_name} record {body.record_id}"
    payload = {"object_name": body.object_name, "record_id": body.record_id, "fields": body.fields}
    return _propose(graph, action_id, "salesforce", "update_record", description, payload)


# -- Jira -----------------------------------------------------------------


@router.post("/jira/search")
def jira_search(body: JiraSearchRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> list[dict]:
    tool = _tool(tools, "jira")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_issues(process_id, jql=body.jql, max_results=body.max_results)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/jira/read")
def jira_read(body: JiraReadRequest, tools: dict[str, BaseTool] = Depends(get_tools)) -> dict:
    tool = _tool(tools, "jira")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.get_issue(process_id, issue_key=body.issue_key)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/jira/create", response_model=RunOutcomeResponse)
def jira_create(
    body: JiraCreateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "jira")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = "Create Jira issue"
    payload = {"fields": body.fields}
    return _propose(graph, action_id, "jira", "create_issue", description, payload)


@router.post("/jira/update", response_model=RunOutcomeResponse)
def jira_update(
    body: JiraUpdateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
) -> RunOutcomeResponse:
    _tool(tools, "jira")
    action_id = _resolve_process_id(body.process_id)
    description = f"Update Jira issue {body.issue_key}"
    payload = {"issue_key": body.issue_key, "fields": body.fields}
    return _propose(graph, action_id, "jira", "update_issue", description, payload)


# -- Shared decision route for every /tools/* write above -------------------


@router.post("/actions/{action_id}/decision", response_model=RunOutcomeResponse)
def decide_action(action_id: str, body: DecisionRequest, graph=Depends(get_action_graph)) -> RunOutcomeResponse:
    try:
        outcome = resume_process(graph, action_id, approved=body.approved)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return to_response(outcome)
