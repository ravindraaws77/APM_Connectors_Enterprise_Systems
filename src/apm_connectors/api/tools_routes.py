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

Every route here sits behind require_caller (router-level `dependencies=`
below) -- a no-op unless APM_API_KEYS is configured (see
api/dependencies.py), at which point every request needs a valid bearer
token. A write/decision route also declares it as a normal parameter to
get the resolved caller name back (FastAPI caches a dependency's result
per request, so this doesn't re-check the token) and thread it into
start_action/resume_process as proposed_by/decided_by.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from apm_connectors.api._responses import to_response, upstream_error
from apm_connectors.api.dependencies import get_action_graph, get_tools, require_caller
from apm_connectors.api.schemas import (
    CalendarCreateEventRequest,
    CalendarReadRequest,
    CalendarSearchRequest,
    DecisionRequest,
    DriveListRequest,
    DriveReadRequest,
    DriveUpdateRequest,
    DriveUploadRequest,
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

router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(require_caller)])


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


def _propose(
    graph,
    process_id: str,
    tool: str,
    method: str,
    description: str,
    payload: dict,
    caller: str | None = None,
) -> RunOutcomeResponse:
    try:
        outcome = start_action(
            graph, process_id, tool=tool, method=method, description=description, payload=payload, proposed_by=caller
        )
    except Exception as exc:
        raise upstream_error(exc) from exc
    return to_response(outcome)


# -- Gmail ----------------------------------------------------------------


@router.post("/gmail/search")
def gmail_search(
    body: GmailSearchRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[dict]:
    tool = _tool(tools, "gmail")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_emails(process_id, query=body.query, max_results=body.max_results, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Search Gmail ({body.query!r}) failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/gmail/read")
def gmail_read(
    body: GmailReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "gmail")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_message(process_id, message_id=body.message_id, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Read Gmail message {body.message_id} failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/gmail/send", response_model=RunOutcomeResponse)
def gmail_send(
    body: GmailSendRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "gmail")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = f"Send email to {body.to}: {body.subject!r}"
    payload = {"to": body.to, "subject": body.subject, "body": body.body}
    return _propose(graph, action_id, "gmail", "send_email", description, payload, caller=caller)


# -- Calendar ---------------------------------------------------------------


@router.post("/calendar/search")
def calendar_search(
    body: CalendarSearchRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[dict]:
    tool = _tool(tools, "google_calendar")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_events(
            process_id,
            query=body.query,
            time_min=body.time_min,
            time_max=body.time_max,
            max_results=body.max_results,
            caller=caller,
        )
    except Exception as exc:
        tool.record_failure(process_id, f"Search Calendar ({body.query!r}) failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/calendar/read")
def calendar_read(
    body: CalendarReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "google_calendar")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_event(process_id, event_id=body.event_id, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Read Calendar event {body.event_id} failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/calendar/create-event", response_model=RunOutcomeResponse)
def calendar_create_event(
    body: CalendarCreateEventRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
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
    return _propose(graph, action_id, "google_calendar", "create_event", description, payload, caller=caller)


# -- Excel --------------------------------------------------------------


@router.post("/excel/worksheets")
def excel_worksheets(
    body: ExcelWorksheetsRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[str]:
    tool = _tool(tools, "excel_file")
    process_id = _resolve_process_id(body.process_id)
    try:
        return tool.list_worksheets(process_id, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"List Excel worksheets failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc


@router.post("/excel/read")
def excel_read(
    body: ExcelReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "excel_file")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_range(process_id, sheet_name=body.sheet_name, address=body.address, caller=caller)
    except Exception as exc:
        tool.record_failure(
            process_id, f"Read Excel range {body.sheet_name}!{body.address} failed: {exc}", caller=caller
        )
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/excel/write", response_model=RunOutcomeResponse)
def excel_write(
    body: ExcelWriteRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "excel_file")
    action_id = _resolve_process_id(body.process_id)
    description = f"Write {len(body.values)} row(s) to {body.sheet_name}!{body.address}"
    payload = {"sheet_name": body.sheet_name, "address": body.address, "values": body.values}
    return _propose(graph, action_id, "excel_file", "write_range", description, payload, caller=caller)


# -- Drive (documents) ---------------------------------------------------


@router.post("/drive/list")
def drive_list(
    body: DriveListRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[dict]:
    tool = _tool(tools, "drive")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.list_files(
            process_id, name_contains=body.name_contains, max_results=body.max_results, caller=caller
        )
    except Exception as exc:
        tool.record_failure(process_id, f"List Drive files failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/drive/read")
def drive_read(
    body: DriveReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "drive")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.read_file(process_id, file_id=body.file_id, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Read Drive file {body.file_id} failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/drive/upload", response_model=RunOutcomeResponse)
def drive_upload(
    body: DriveUploadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "drive")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = f"Upload document '{body.name}' ({body.mime_type}) to Drive"
    payload = {"name": body.name, "content_base64": body.content_base64, "mime_type": body.mime_type}
    return _propose(graph, action_id, "drive", "upload_file", description, payload, caller=caller)


@router.post("/drive/update", response_model=RunOutcomeResponse)
def drive_update(
    body: DriveUpdateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "drive")
    action_id = _resolve_process_id(body.process_id)
    description = f"Replace contents of Drive file {body.file_id}"
    payload = {"file_id": body.file_id, "content_base64": body.content_base64}
    return _propose(graph, action_id, "drive", "update_file", description, payload, caller=caller)


# -- Salesforce ---------------------------------------------------------


@router.post("/salesforce/query")
def salesforce_query(
    body: SalesforceQueryRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[dict]:
    tool = _tool(tools, "salesforce")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.query_records(process_id, soql=body.soql, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Query Salesforce ({body.soql!r}) failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/salesforce/read")
def salesforce_read(
    body: SalesforceReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "salesforce")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.get_record(process_id, object_name=body.object_name, record_id=body.record_id, caller=caller)
    except Exception as exc:
        tool.record_failure(
            process_id, f"Read Salesforce {body.object_name} {body.record_id} failed: {exc}", caller=caller
        )
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/salesforce/create", response_model=RunOutcomeResponse)
def salesforce_create(
    body: SalesforceCreateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "salesforce")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = f"Create Salesforce {body.object_name} record"
    payload = {"object_name": body.object_name, "fields": body.fields}
    return _propose(graph, action_id, "salesforce", "create_record", description, payload, caller=caller)


@router.post("/salesforce/update", response_model=RunOutcomeResponse)
def salesforce_update(
    body: SalesforceUpdateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "salesforce")
    action_id = _resolve_process_id(body.process_id)
    description = f"Update Salesforce {body.object_name} record {body.record_id}"
    payload = {"object_name": body.object_name, "record_id": body.record_id, "fields": body.fields}
    return _propose(graph, action_id, "salesforce", "update_record", description, payload, caller=caller)


# -- Jira -----------------------------------------------------------------


@router.post("/jira/search")
def jira_search(
    body: JiraSearchRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> list[dict]:
    tool = _tool(tools, "jira")
    process_id = _resolve_process_id(body.process_id)
    try:
        results = tool.search_issues(process_id, jql=body.jql, max_results=body.max_results, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Search Jira ({body.jql!r}) failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return [r.__dict__ for r in results]


@router.post("/jira/read")
def jira_read(
    body: JiraReadRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    caller: str | None = Depends(require_caller),
) -> dict:
    tool = _tool(tools, "jira")
    process_id = _resolve_process_id(body.process_id)
    try:
        result = tool.get_issue(process_id, issue_key=body.issue_key, caller=caller)
    except Exception as exc:
        tool.record_failure(process_id, f"Read Jira issue {body.issue_key} failed: {exc}", caller=caller)
        raise upstream_error(exc) from exc
    return result.__dict__


@router.post("/jira/create", response_model=RunOutcomeResponse)
def jira_create(
    body: JiraCreateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "jira")  # fail fast, before recording a pending action doomed to fail on approval
    action_id = _resolve_process_id(body.process_id)
    description = "Create Jira issue"
    payload = {"fields": body.fields}
    return _propose(graph, action_id, "jira", "create_issue", description, payload, caller=caller)


@router.post("/jira/update", response_model=RunOutcomeResponse)
def jira_update(
    body: JiraUpdateRequest,
    tools: dict[str, BaseTool] = Depends(get_tools),
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    _tool(tools, "jira")
    action_id = _resolve_process_id(body.process_id)
    description = f"Update Jira issue {body.issue_key}"
    payload = {"issue_key": body.issue_key, "fields": body.fields}
    return _propose(graph, action_id, "jira", "update_issue", description, payload, caller=caller)


# -- Shared decision route for every /tools/* write above -------------------


@router.post("/actions/{action_id}/decision", response_model=RunOutcomeResponse)
def decide_action(
    action_id: str,
    body: DecisionRequest,
    graph=Depends(get_action_graph),
    caller: str | None = Depends(require_caller),
) -> RunOutcomeResponse:
    try:
        outcome = resume_process(graph, action_id, approved=body.approved, decided_by=caller)
    except Exception as exc:
        raise upstream_error(exc) from exc
    return to_response(outcome)
