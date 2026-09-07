"""MCP server exposing apm_connectors' /tools/* API as tools for a
reasoning agent -- one process, one tool per REST route
(docs/api-contract.md), the agent-facing side of the "connectors stay
reasoning-free" split this package's CLAUDE.md commits to. This module
talks to that API purely over HTTP (apm_connectors_mcp.client.
ConnectorClient) -- it never imports apm_connectors.tools/graph
directly, so it can run anywhere the /tools/* server is reachable,
deployed independently of it.

Run standalone (stdio transport, for a local agent host like Claude
Desktop or Claude Code's MCP config) once the /tools/* API is already
running elsewhere:

    pip install -e ".[mcp]"
    APM_CONNECTORS_BASE_URL=http://127.0.0.1:8000 apm-connectors-mcp

Every write tool (gmail_send, calendar_create_event, excel_write,
salesforce_create, salesforce_update, jira_create, jira_update) mirrors
the REST API exactly: it does not execute anything -- it
returns a paused action_id, and the agent must call
decide_action(action_id, approved=True) to actually run it. That gate
is enforced server-side in the /tools/* API regardless of what this
MCP layer does, so it can't be bypassed by a misbehaving or
adversarial agent -- this module is a description/transport
convenience on top of it, not a second copy of the guardrail.

Tool descriptions below are deliberately detailed (Gmail's query
syntax, RFC3339 datetime format, action_id vs. process_id) -- this is
the vocabulary an LLM-based agent uses to translate a free-text
request ("what's the status of order 401") into an actual call
(gmail_search(query="order 401")) on its own, which is the whole point
of exposing these as MCP tools instead of a raw HTTP contract a
hand-written intent parser would have to keep in sync by hand.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from apm_connectors_mcp.client import ConnectorAPIError, ConnectorClient


def build_server(client: ConnectorClient, name: str = "apm-connectors") -> MCPServer:
    """Registers every /tools/* route as an MCP tool against `client`.
    A factory rather than a module-level singleton so tests (or a
    caller that wants a non-default ConnectorClient) can inject one --
    same shape as apm_connectors.graph.build_action_graph(tools, ...).
    """
    mcp = MCPServer(name)

    async def _call(path: str, body: dict[str, Any]) -> Any:
        try:
            return await client.post(path, body)
        except ConnectorAPIError as exc:
            # ToolError is what MCP converts into a clean is_error result
            # for the agent to see, rather than a raw/uncaught exception.
            raise ToolError(str(exc)) from exc

    # -- Gmail ------------------------------------------------------------

    @mcp.tool()
    async def gmail_search(query: str = "", max_results: int = 10, process_id: str | None = None) -> list[dict]:
        """Search Gmail. `query` is free text -- Gmail's search syntax
        works if used ("from:x@y.com", "newer_than:7d", "is:unread",
        "subject:invoice"), but plain keywords work too, same as
        typing into the Gmail search box. Pass "" (the default) for no
        filter at all -- the most recent `max_results` messages.
        Read-only: executes immediately, no approval needed.
        """
        return await _call(
            "/tools/gmail/search", {"query": query, "max_results": max_results, "process_id": process_id}
        )

    @mcp.tool()
    async def gmail_read(message_id: str, process_id: str | None = None) -> dict[str, Any]:
        """Read one Gmail message by id (from gmail_search's results).
        Read-only: executes immediately, no approval needed.
        """
        return await _call("/tools/gmail/read", {"message_id": message_id, "process_id": process_id})

    @mcp.tool()
    async def gmail_send(to: str, subject: str, body: str, process_id: str | None = None) -> dict[str, Any]:
        """Propose sending a Gmail email. This does NOT send anything
        -- it pauses for human approval and returns action_id in the
        response. Call decide_action with that action_id and
        approved=true to actually send it, or approved=false to
        discard it; nothing goes out either way until that call.
        """
        return await _call(
            "/tools/gmail/send", {"to": to, "subject": subject, "body": body, "process_id": process_id}
        )

    # -- Google Calendar ----------------------------------------------------

    @mcp.tool()
    async def calendar_search(
        query: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        process_id: str | None = None,
    ) -> list[dict]:
        """Search/list Google Calendar events, optionally filtered by
        free-text query and/or an RFC3339 time window (e.g.
        time_min="2026-09-01T00:00:00Z"). Omit all filters to list
        upcoming events. Read-only: executes immediately.
        """
        return await _call(
            "/tools/calendar/search",
            {
                "query": query,
                "time_min": time_min,
                "time_max": time_max,
                "max_results": max_results,
                "process_id": process_id,
            },
        )

    @mcp.tool()
    async def calendar_read(event_id: str, process_id: str | None = None) -> dict[str, Any]:
        """Read one Calendar event by id (from calendar_search's
        results). Read-only: executes immediately.
        """
        return await _call("/tools/calendar/read", {"event_id": event_id, "process_id": process_id})

    @mcp.tool()
    async def calendar_create_event(
        title: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        location: str | None = None,
        process_id: str | None = None,
    ) -> dict[str, Any]:
        """Propose creating a single (non-recurring) Calendar event.
        `start`/`end` are RFC3339 datetimes (e.g.
        "2026-09-10T15:00:00Z"). This does NOT create anything -- it
        pauses for approval and returns action_id; call decide_action
        to resolve it.
        """
        return await _call(
            "/tools/calendar/create-event",
            {
                "title": title,
                "start": start,
                "end": end,
                "attendees": attendees,
                "location": location,
                "process_id": process_id,
            },
        )

    # -- Excel (local file or Google Drive .xlsx) ----------------------------

    @mcp.tool()
    async def excel_worksheets(process_id: str | None = None) -> list[str]:
        """List worksheet names in the workbook this server is
        configured for (APM_EXCEL_WORKBOOK_PATH or
        APM_EXCEL_DRIVE_FILE_ID). Read-only: executes immediately.
        """
        return await _call("/tools/excel/worksheets", {"process_id": process_id})

    @mcp.tool()
    async def excel_read(
        sheet_name: str | None = None, address: str | None = None, process_id: str | None = None
    ) -> dict[str, Any]:
        """Read a cell range from the configured workbook. Omit
        sheet_name/address for the workbook's first worksheet and its
        whole used range. Read-only: executes immediately.
        """
        return await _call(
            "/tools/excel/read", {"sheet_name": sheet_name, "address": address, "process_id": process_id}
        )

    @mcp.tool()
    async def excel_write(
        sheet_name: str, address: str, values: list[list[Any]], process_id: str | None = None
    ) -> dict[str, Any]:
        """Propose overwriting a cell range, e.g. address="A1:B2",
        values=[["x", "y"], ["1", "2"]]. This does NOT write anything
        -- it pauses for approval and returns action_id; call
        decide_action to resolve it.
        """
        return await _call(
            "/tools/excel/write",
            {"sheet_name": sheet_name, "address": address, "values": values, "process_id": process_id},
        )

    # -- Salesforce ---------------------------------------------------------

    @mcp.tool()
    async def salesforce_query(soql: str, process_id: str | None = None) -> list[dict]:
        """Run a read-only Salesforce SOQL query, e.g. "SELECT Id, Name,
        StageName FROM Opportunity WHERE StageName = 'Negotiation' LIMIT
        20". Cap result size with SOQL's own LIMIT clause. Read-only:
        executes immediately, no approval needed.
        """
        return await _call("/tools/salesforce/query", {"soql": soql, "process_id": process_id})

    @mcp.tool()
    async def salesforce_read(object_name: str, record_id: str, process_id: str | None = None) -> dict[str, Any]:
        """Read one Salesforce record by its object type (e.g.
        "Opportunity", "Contact", "Lead") and id (from salesforce_query's
        results). Read-only: executes immediately.
        """
        return await _call(
            "/tools/salesforce/read", {"object_name": object_name, "record_id": record_id, "process_id": process_id}
        )

    @mcp.tool()
    async def salesforce_create(
        object_name: str, fields: dict[str, Any], process_id: str | None = None
    ) -> dict[str, Any]:
        """Propose creating a new Salesforce record, e.g.
        object_name="Lead", fields={"LastName": "Doe", "Company": "Acme"}.
        This does NOT create anything -- it pauses for human approval and
        returns action_id in the response. Call decide_action with that
        action_id and approved=true to actually create it, or
        approved=false to discard it.
        """
        return await _call(
            "/tools/salesforce/create", {"object_name": object_name, "fields": fields, "process_id": process_id}
        )

    @mcp.tool()
    async def salesforce_update(
        object_name: str, record_id: str, fields: dict[str, Any], process_id: str | None = None
    ) -> dict[str, Any]:
        """Propose updating an existing Salesforce record's fields, e.g.
        object_name="Opportunity", record_id="006...",
        fields={"StageName": "Closed Won"}. This does NOT update anything
        -- it pauses for approval and returns action_id; call
        decide_action to resolve it.
        """
        return await _call(
            "/tools/salesforce/update",
            {"object_name": object_name, "record_id": record_id, "fields": fields, "process_id": process_id},
        )

    # -- Jira -----------------------------------------------------------------

    @mcp.tool()
    async def jira_search(jql: str, max_results: int = 50, process_id: str | None = None) -> list[dict]:
        """Run a read-only Jira JQL search, e.g. "project = OPS AND
        status = 'In Progress' ORDER BY updated DESC". Cap result size
        with max_results. Read-only: executes immediately, no approval
        needed.
        """
        return await _call(
            "/tools/jira/search", {"jql": jql, "max_results": max_results, "process_id": process_id}
        )

    @mcp.tool()
    async def jira_read(issue_key: str, process_id: str | None = None) -> dict[str, Any]:
        """Read one Jira issue by its key (e.g. "OPS-42", from
        jira_search's results). Read-only: executes immediately.
        """
        return await _call("/tools/jira/read", {"issue_key": issue_key, "process_id": process_id})

    @mcp.tool()
    async def jira_create(fields: dict[str, Any], process_id: str | None = None) -> dict[str, Any]:
        """Propose creating a new Jira issue. `fields` is the Jira
        `fields` payload as-is, e.g. {"project": {"key": "OPS"},
        "summary": "Fix the thing", "issuetype": {"name": "Bug"}}. This
        does NOT create anything -- it pauses for human approval and
        returns action_id in the response. Call decide_action with that
        action_id and approved=true to actually create it, or
        approved=false to discard it.
        """
        return await _call("/tools/jira/create", {"fields": fields, "process_id": process_id})

    @mcp.tool()
    async def jira_update(issue_key: str, fields: dict[str, Any], process_id: str | None = None) -> dict[str, Any]:
        """Propose updating an existing Jira issue's fields, e.g.
        issue_key="OPS-42", fields={"summary": "Updated title"}. This
        does NOT update anything -- it pauses for approval and returns
        action_id; call decide_action to resolve it.
        """
        return await _call(
            "/tools/jira/update", {"issue_key": issue_key, "fields": fields, "process_id": process_id}
        )

    # -- Shared decision route for every write above -------------------------

    @mcp.tool()
    async def decide_action(action_id: str, approved: bool) -> dict[str, Any]:
        """Approve or reject a pending write proposed by gmail_send,
        calendar_create_event, excel_write, salesforce_create/update, or
        jira_create/update (its action_id from that call's response).
        Nothing in the real system happens until this is called with
        approved=true; approved=false discards it -- nothing is
        sent/created/written either way.
        """
        return await _call(f"/tools/actions/{action_id}/decision", {"approved": approved})

    return mcp


def main() -> None:
    client = ConnectorClient()
    mcp = build_server(client)
    transport = os.environ.get("APM_CONNECTORS_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
