"""Tests for apm_connectors_mcp -- the MCP server exposing /tools/* as
agent tools. Exercises it end to end against a real FastAPI app (fake
tools injected via dependency_overrides, same fixtures as
tests/test_tools_api.py) through an httpx.ASGITransport, so this
covers the real route handlers/validation with no live server process,
network, or credentials involved -- see ConnectorClient's docstring
for why that hook exists.
"""

from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from mcp.server.mcpserver.exceptions import ToolError

from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_action_graph, get_tools
from apm_connectors.graph import build_action_graph
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.excel_file_tool import ExcelFileTool
from apm_connectors.tools.gmail_tool import GmailTool
from apm_connectors.tools.jira_tool import JiraTool
from apm_connectors.tools.salesforce_tool import SalesforceTool
from apm_connectors_mcp.client import ConnectorClient
from apm_connectors_mcp.server import build_server
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes
from tests.test_gmail_tool import FakeGmailClient, _raw_message
from tests.test_jira_tool import FakeJiraClient, _raw_issue
from tests.test_salesforce_tool import FakeSalesforceClient, _raw_record


def _mcp(
    tmp_path: Path,
    with_excel: bool = True,
    with_salesforce: bool = True,
    with_jira: bool = True,
    gmail_messages: list | None = None,
):
    """Same fake-tool wiring as tests/test_tools_api.py's _client, but
    reachable through the MCP server instead of a plain TestClient.
    """
    store = StateStore(tmp_path / "state.json")
    gmail_client = FakeGmailClient(gmail_messages or [])
    calendar_client = FakeCalendarClient([])
    tools = {
        "gmail": GmailTool(store, gmail_client),
        "google_calendar": CalendarTool(store, calendar_client),
    }
    excel_source = None
    if with_excel:
        excel_source = FakeWorkbookSource(_sample_workbook_bytes())
        tools["excel_file"] = ExcelFileTool(store, excel_source)
    salesforce_client = None
    if with_salesforce:
        salesforce_client = FakeSalesforceClient(
            [_raw_record("006abc", "Opportunity", Name="Acme Renewal", StageName="Negotiation")]
        )
        tools["salesforce"] = SalesforceTool(store, salesforce_client)
    jira_client = None
    if with_jira:
        jira_client = FakeJiraClient([_raw_issue("OPS-1", "Bug", summary="Payments failing")])
        tools["jira"] = JiraTool(store, jira_client)
    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

    app = create_app()
    app.dependency_overrides[get_tools] = lambda: tools
    app.dependency_overrides[get_action_graph] = lambda: action_graph

    client = ConnectorClient(base_url="http://testserver", transport=httpx.ASGITransport(app=app))
    mcp = build_server(client)
    return mcp, store, gmail_client, calendar_client, excel_source, salesforce_client, jira_client


@pytest.mark.anyio
async def test_lists_one_tool_per_tools_route(tmp_path: Path) -> None:
    mcp, *_ = _mcp(tmp_path)

    tools = await mcp.list_tools()

    names = {t.name for t in tools}
    assert names == {
        "gmail_search",
        "gmail_read",
        "gmail_send",
        "calendar_search",
        "calendar_read",
        "calendar_create_event",
        "excel_worksheets",
        "excel_read",
        "excel_write",
        "salesforce_query",
        "salesforce_read",
        "salesforce_create",
        "salesforce_update",
        "jira_search",
        "jira_read",
        "jira_create",
        "jira_update",
        "decide_action",
    }


@pytest.mark.anyio
async def test_gmail_search_returns_data_immediately(tmp_path: Path) -> None:
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    mcp, store, *_ = _mcp(tmp_path, gmail_messages=[message])

    result = await mcp.call_tool("gmail_search", {"query": "newer_than:7d"})

    assert result.is_error is False
    assert len(result.structured_content["result"]) == 1
    assert result.structured_content["result"][0]["subject"] == "Hi"


@pytest.mark.anyio
async def test_gmail_search_with_no_query_still_works(tmp_path: Path) -> None:
    """The MCP tool defaults query to "" (no filter) -- an agent can
    call gmail_search() with nothing at all.
    """
    message = _raw_message("m1", sender="a@b.com", subject="Hi", snippet="hello", date="2026-09-01")
    mcp, *_ = _mcp(tmp_path, gmail_messages=[message])

    result = await mcp.call_tool("gmail_search", {})

    assert result.is_error is False
    assert len(result.structured_content["result"]) == 1


@pytest.mark.anyio
async def test_unconfigured_tool_raises_tool_error(tmp_path: Path) -> None:
    """A 503 from the API (tool not configured) surfaces as a ToolError
    -- the clean, agent-visible error MCP is designed to convert into
    an is_error result over a real transport, not a raw exception.
    """
    mcp, *_ = _mcp(tmp_path, with_excel=False)

    with pytest.raises(ToolError, match="tool not configured"):
        await mcp.call_tool("excel_worksheets", {})


@pytest.mark.anyio
async def test_gmail_send_pauses_then_decide_action_executes(tmp_path: Path) -> None:
    mcp, store, gmail_client, *_ = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "gmail_send", {"to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."}
    )
    assert propose.is_error is False
    action_id = propose.structured_content["action_id"]
    assert propose.structured_content["pending_action"] is not None
    assert gmail_client.sent == []

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": True})

    assert decide.is_error is False
    assert decide.structured_content["final_result"]["executed"] is True
    assert len(gmail_client.sent) == 1


@pytest.mark.anyio
async def test_gmail_send_rejected_does_not_execute(tmp_path: Path) -> None:
    mcp, store, gmail_client, *_ = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "gmail_send", {"to": "customer@realcorp.io", "subject": "Update", "body": "Hi there."}
    )
    action_id = propose.structured_content["action_id"]

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": False})

    assert decide.structured_content["final_result"] == {"executed": False, "reason": "rejected"}
    assert gmail_client.sent == []


@pytest.mark.anyio
async def test_salesforce_query_returns_data_immediately(tmp_path: Path) -> None:
    mcp, *_ = _mcp(tmp_path)

    result = await mcp.call_tool("salesforce_query", {"soql": "SELECT Id, Name FROM Opportunity"})

    assert result.is_error is False
    assert len(result.structured_content["result"]) == 1
    assert result.structured_content["result"][0]["record_id"] == "006abc"


@pytest.mark.anyio
async def test_salesforce_unconfigured_raises_tool_error(tmp_path: Path) -> None:
    mcp, *_ = _mcp(tmp_path, with_salesforce=False)

    with pytest.raises(ToolError, match="tool not configured"):
        await mcp.call_tool("salesforce_query", {"soql": "SELECT Id FROM Opportunity"})


@pytest.mark.anyio
async def test_salesforce_create_pauses_then_decide_action_executes(tmp_path: Path) -> None:
    mcp, store, _, _, _, salesforce_client, _ = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "salesforce_create", {"object_name": "Lead", "fields": {"LastName": "Doe", "Company": "Acme"}}
    )
    assert propose.is_error is False
    action_id = propose.structured_content["action_id"]
    assert propose.structured_content["pending_action"] is not None
    assert salesforce_client.created == []

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": True})

    assert decide.is_error is False
    assert decide.structured_content["final_result"]["executed"] is True
    assert len(salesforce_client.created) == 1


@pytest.mark.anyio
async def test_salesforce_update_rejected_does_not_execute(tmp_path: Path) -> None:
    mcp, store, _, _, _, salesforce_client, _ = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "salesforce_update",
        {"object_name": "Opportunity", "record_id": "006abc", "fields": {"StageName": "Closed Won"}},
    )
    action_id = propose.structured_content["action_id"]

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": False})

    assert decide.structured_content["final_result"] == {"executed": False, "reason": "rejected"}
    assert salesforce_client.updated == []


@pytest.mark.anyio
async def test_jira_search_returns_data_immediately(tmp_path: Path) -> None:
    mcp, *_ = _mcp(tmp_path)

    result = await mcp.call_tool("jira_search", {"jql": "project = OPS"})

    assert result.is_error is False
    assert len(result.structured_content["result"]) == 1
    assert result.structured_content["result"][0]["issue_key"] == "OPS-1"


@pytest.mark.anyio
async def test_jira_unconfigured_raises_tool_error(tmp_path: Path) -> None:
    mcp, *_ = _mcp(tmp_path, with_jira=False)

    with pytest.raises(ToolError, match="tool not configured"):
        await mcp.call_tool("jira_search", {"jql": "project = OPS"})


@pytest.mark.anyio
async def test_jira_create_pauses_then_decide_action_executes(tmp_path: Path) -> None:
    mcp, store, _, _, _, _, jira_client = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "jira_create",
        {"fields": {"project": {"key": "OPS"}, "summary": "Fix the thing", "issuetype": {"name": "Bug"}}},
    )
    assert propose.is_error is False
    action_id = propose.structured_content["action_id"]
    assert propose.structured_content["pending_action"] is not None
    assert jira_client.created == []

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": True})

    assert decide.is_error is False
    assert decide.structured_content["final_result"]["executed"] is True
    assert len(jira_client.created) == 1


@pytest.mark.anyio
async def test_jira_update_rejected_does_not_execute(tmp_path: Path) -> None:
    mcp, store, _, _, _, _, jira_client = _mcp(tmp_path)

    propose = await mcp.call_tool(
        "jira_update", {"issue_key": "OPS-1", "fields": {"summary": "Updated title"}}
    )
    action_id = propose.structured_content["action_id"]

    decide = await mcp.call_tool("decide_action", {"action_id": action_id, "approved": False})

    assert decide.structured_content["final_result"] == {"executed": False, "reason": "rejected"}
    assert jira_client.updated == []


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
