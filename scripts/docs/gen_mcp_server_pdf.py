# -*- coding: utf-8 -*-
"""Generate 'MCP Server Layer — apm_connectors_mcp/' reference PDF.
One of the per-layer reference docs described in CLAUDE.md's
"Reference documents" section and scripts/docs/README.md. Uses the
shared Platypus template in _pdf_template.py -- see that file (and the
README) before writing a new per-layer script from scratch.

Run from anywhere with `pip install reportlab` on the path:

    python scripts/docs/gen_mcp_server_pdf.py

Writes docs/mcp-server-reference.pdf by default (override via the
OUT_OVERRIDE env var). Re-run after any change to
src/apm_connectors_mcp/{client,server}.py to keep this in sync --
regenerate from current source rather than hand-editing stale prose.
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from _pdf_template import (
    AMBER, BLUE, CODE_BORDER, GRAY, GRAY_FILL, GREEN, INK, MARGIN, RED, USABLE_W,
    bl, caption, code_block, esc, footer, h1, quote_block, rule, simple_table, styles,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("OUT_OVERRIDE", REPO_ROOT / "docs" / "mcp-server-reference.pdf"))

story = []

# ---------------------------------------------------------------------------
story.append(Paragraph("MCP Server Layer — apm_connectors_mcp/", styles["title"]))
story.append(Paragraph(
    "A from-basics walkthrough of the separate package that exposes the /tools/* API as MCP tools for "
    "an LLM-based agent — the natural-language front door, and why it needed no new enforcement code.",
    styles["subtitle"],
))
story.append(rule())

# 1
story.append(h1("1. The problem this layer solves — a structural fact worth noticing first"))
story.append(bl(
    "Every layer covered so far (FastAPI, Action Graph, Connector Layer, State Store, Terraform) lives "
    "inside one Python package, apm_connectors. This layer does not. It's src/apm_connectors_mcp/ — a "
    "<b>separate top-level package</b>, with its own mcp extra in pyproject.toml "
    "(mcp = [\"mcp&gt;=2.0\", \"httpx&gt;=0.27\"]) and its own console-script entry point "
    "(apm-connectors-mcp = \"apm_connectors_mcp.server:main\"). That's not incidental organization — "
    "it's the clearest physical evidence yet of the principle stated in this repo's CLAUDE.md: "
    "“connectors stay reasoning-free... whatever reasoning layer consumes them is deployed "
    "separately.” This package can be installed, run, and executed on a completely different machine "
    "from the /tools/* API server it talks to, with a completely different, much smaller dependency "
    "set (no googleapiclient, no requests, no langgraph — just httpx and mcp)."
))
story.append(bl(
    "The problem it solves: an LLM-based agent host (Claude Desktop, Claude Code, or any MCP-capable "
    "client) doesn't speak raw HTTP + hand-parsed JSON. It speaks <b>MCP</b> — a protocol specifically "
    "designed for an LLM to discover a set of callable “tools,” each with a name, a typed schema, and a "
    "natural-language description, and decide on its own which to call based on a free-text request. "
    "This layer's whole job is exposing the exact same /tools/* contract already covered, through that "
    "different vocabulary, to that different kind of caller."
))

# 2
story.append(h1("2. MCP basics, since this builds on it"))
story.append(bl("MCP (Model Context Protocol) is a standard for connecting an LLM-based agent host to external capabilities. Three ideas matter here:"))
mcp_rows = [
    ["<b>Concept</b>", "<b>What it means</b>"],
    ["Tool", "A callable action a server exposes — name, typed parameters, a docstring, a declared return shape. Unlike a plain Python function, an MCP tool's schema and description are read by the LLM at decision time to decide whether and how to call it."],
    ["Server / Host", "The server (this package) exposes tools; the host (Claude Desktop, Claude Code, etc.) is the LLM-facing application that connects to servers and lets the model call their tools."],
    ["Transport", "How host and server actually talk — stdio (local subprocess, stdin/stdout; the default for a locally-configured agent host) or sse/streamable-http (a network service instead, for a remote reasoning layer)."],
]
story.append(simple_table(mcp_rows, [1.5 * inch, USABLE_W - 1.5 * inch]))
story.append(caption("A minimal MCP tool — the pattern this file repeats twenty-two times"))
story.append(code_block(
    "@mcp.tool()\n"
    "async def my_tool(x: int) -> dict:\n"
    '    """A description the LLM reads to decide when/how to call this."""\n'
    '    return {"result": x * 2}\n'
))
story.append(bl(
    "The framework introspects the function signature for the parameter schema and uses the docstring "
    "as the tool's description — both become part of what the connected LLM actually sees when "
    "deciding what to call. Worth sitting with, because it's the single most distinctive thing about "
    "this layer versus every other one covered so far (§5)."
))

# 3
story.append(h1("3. Pattern: a pure HTTP adapter, never touching the layers it fronts"))
story.append(quote_block(
    "“Thin async HTTP client for apm_connectors' /tools/* API — the only thing apm_connectors_mcp "
    "talks to. Deliberately dumb: it never imports apm_connectors.tools/graph directly, so this "
    "package can run anywhere with just httpx + mcp installed, against a /tools/* server deployed "
    "wherever.”"
))
story.append(bl(
    "ConnectorClient (client.py) is genuinely minimal — one constructor, a post method for the /tools/* "
    "routes and a get method for the read-only /processes/* routes (§8), ~40 lines of real logic. It has "
    "no knowledge of GmailTool, BaseTool, graph.py, or StateStore. Every one of the "
    "other five layers this document set has covered is, from this package's point of view, just "
    "“whatever's running behind APM_CONNECTORS_BASE_URL.” This is the same “depend on the API contract, "
    "not the implementation” discipline the State Store reference called a <i>migration seam</i> — here "
    "it's drawn at a much bigger scale: not just swappable storage, but a swappable, "
    "independently-deployable <i>process</i>."
))
story.append(code_block(
    "class ConnectorClient:\n"
    "    def __init__(\n"
    "        self,\n"
    "        base_url: str | None = None,\n"
    "        transport: httpx.AsyncBaseTransport | None = None,\n"
    "        api_key: str | None = None,\n"
    "    ) -> None:\n"
    '        api_key = api_key or os.environ.get("APM_CONNECTORS_API_KEY")\n'
    '        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None\n'
    "        self._client = httpx.AsyncClient(\n"
    '            base_url=base_url or os.environ.get("APM_CONNECTORS_BASE_URL", DEFAULT_BASE_URL),\n'
    "            timeout=30.0,\n"
    "            transport=transport,\n"
    "            headers=headers,\n"
    "        )\n"
))
story.append(bl(
    "Three configuration surfaces worth naming: base_url defaults to APM_CONNECTORS_BASE_URL, falling "
    "back to 127.0.0.1:8000 (the same default docs/running-locally.md uses) — so a locally-run MCP "
    "server talks to a locally-run API server with zero configuration, but pointing it at a remote "
    "deployment (say, the ECS Fargate service_url from the Terraform reference) is a single environment "
    "variable, no code change. api_key (APM_CONNECTORS_API_KEY) is sent as a bearer token, needed only "
    "once the server it points at has APM_API_KEYS configured; it identifies this process as a caller like "
    "any other, with no extra privilege. transport is the testing hook — covered fully in §9."
))

# 4
story.append(h1("4. Pattern: a factory function, again, for the same reason as every other layer"))
story.append(code_block(
    "def build_server(client: ConnectorClient, name: str = \"apm-connectors\") -> MCPServer:\n"
    '    """Registers every /tools/* route as an MCP tool against `client`.\n'
    "    A factory rather than a module-level singleton so tests (or a\n"
    "    caller that wants a non-default ConnectorClient) can inject one --\n"
    "    same shape as apm_connectors.graph.build_action_graph(tools, ...).\"\"\"\n"
    "    mcp = MCPServer(name)\n"
    "    ...\n"
    "    return mcp\n"
))
story.append(bl(
    "By now this should look familiar: dependencies.py's get_tools()/get_action_graph() were factories "
    "taking dependencies as parameters; graph.py's build_action_graph(tools, state_store, checkpointer) "
    "was the same shape; here it's build_server(client). Same recurring need across every layer in this "
    "codebase — swap what's plugged in without touching the logic that uses it — expressed once more, "
    "this time for an MCPServer instance instead of a FastAPI app or a compiled graph."
))

# 5
story.append(h1("5. Pattern: the docstring as a machine-consumed interface, not just documentation"))
story.append(bl("This is the pattern genuinely unique to this layer. Compare two docstrings side by side:"))
story.append(caption("gmail_tool.py (Connector Layer) — documentation for a human reading the source"))
story.append(code_block(
    "def search_emails(self, process_id: str, query: str, max_results: int = 10) -> list[EmailSummary]:\n"
    '    """Search the mailbox using Gmail\'s query syntax..."""\n'
))
story.append(caption("server.py (this layer) — read by the LLM agent deciding whether/how to call this"))
story.append(code_block(
    "@mcp.tool()\n"
    "async def gmail_search(query: str = \"\", max_results: int = 10, process_id: str | None = None) -> list[dict]:\n"
    '    """Search Gmail. `query` is free text -- Gmail\'s search syntax\n'
    '    works if used ("from:x@y.com", "newer_than:7d", "is:unread",\n'
    '    "subject:invoice"), but plain keywords work too, same as\n'
    '    typing into the Gmail search box. Pass "" (the default) for no\n'
    "    filter at all -- the most recent `max_results` messages.\n"
    '    Read-only: executes immediately, no approval needed.\n'
    '    """\n'
))
story.append(quote_block(
    "“Tool descriptions below are deliberately detailed (Gmail's query syntax, RFC3339 datetime "
    "format, action_id vs. process_id) — this is the vocabulary an LLM-based agent uses to translate a "
    "free-text request ('what's the status of order 401') into an actual call "
    "(gmail_search(query='order 401')) on its own, which is the whole point of exposing these as MCP "
    "tools instead of a raw HTTP contract a hand-written intent parser would have to keep in sync by "
    "hand.”"
))
story.append(bl(
    "This reframes what a docstring <i>is</i>, at this layer specifically. Everywhere else in this "
    "codebase, a docstring is for the next engineer reading the file. Here, it's runtime-consumed input "
    "to a model's decision about whether to call this tool and with what arguments — closer to a prompt "
    "than to a comment. That's also why every write tool's docstring repeats the same explicit warning "
    "almost verbatim (“This does NOT send anything — it pauses for human approval and returns action_id. "
    "A human approves or rejects it outside this agent”) rather than relying "
    "on a shared reference: an LLM reads <i>this</i> tool's description in isolation when deciding how "
    "to act, so the safety-relevant fact has to be restated locally, every time."
))

# 6
story.append(h1("6. Pattern: the approval gate — and who is allowed to open it"))
story.append(quote_block(
    "“Every write tool... mirrors the REST API exactly: it does not execute anything — it returns a "
    "paused action_id. This server deliberately has NO tool that approves or rejects that action: the "
    "decision route (POST /tools/actions/{action_id}/decision) belongs to a human, through a human-facing "
    "review surface, never to the agent that proposed the write. An agent that could call it would be "
    "approving its own writes, which is exactly what this package's non-negotiable rule forbids.”"
))
story.append(bl("Look at what gmail_send actually does here:"))
story.append(code_block(
    "@mcp.tool()\n"
    "async def gmail_send(to: str, subject: str, body: str, process_id: str | None = None) -> dict[str, Any]:\n"
    '    """Propose sending a Gmail email. This does NOT send anything\n'
    "    -- it pauses for human approval and returns action_id. A human approves or rejects it\n"
    "    outside this agent; check progress with action_status(action_id).\n"
    '    Nothing goes out unless a human approves it.\n'
    '    """\n'
    '    return await _call(\n'
    '        "/tools/gmail/send", {"to": to, "subject": subject, "body": body, "process_id": process_id}\n'
    '    )\n'
))
story.append(bl(
    "It's an HTTP POST to /tools/gmail/send — the exact same route covered in the FastAPI reference, "
    "hitting the exact same _propose() → start_action() → propose_node → approval_node[interrupt()] "
    "pipeline covered in the Action Graph reference. The server-side gate guarantees that nothing executes "
    "until <i>someone</i> calls the decision route. It cannot tell <i>who</i> that someone is — so the "
    "gate is only meaningful if the caller that proposes a write can't also be the one that approves it."
))
story.append(bl(
    "That is the one thing this layer has to get right, and it gets it right by omission. This package "
    "<b>originally shipped with a decide_action tool</b> that called the decision route — which meant an "
    "LLM agent (hallucinating, or deliberately prompt-injected by the email it was reading) could propose a "
    "write and approve it in the same breath, turning a human approval gate into an agent-only loop. It was "
    "removed. Today an agent here has strictly less power than a human with an API key: it can read, and "
    "it can propose, but every proposal waits for a decision that has to come from outside this process."
))

# 7
story.append(h1("7. Pattern: error translation — a fourth link in a chain you've seen at every layer"))
story.append(bl("Trace one failure all the way through, since you've now seen each individual link in earlier references:"))
story.append(code_block(
    "# apm_connectors/api/_responses.py (FastAPI layer)\n"
    "def upstream_error(exc: Exception) -> HTTPException:\n"
    '    return HTTPException(status_code=502, detail=f"Upstream tool error: {exc}")\n\n'
    "# apm_connectors_mcp/client.py (this layer)\n"
    "class ConnectorAPIError(Exception): ...\n\n"
    "async def post(self, path: str, body: dict[str, Any]) -> Any:\n"
    "    response = await self._client.post(path, json=body)\n"
    "    if response.status_code >= 400:\n"
    "        raise ConnectorAPIError(response.status_code, _extract_detail(response))\n"
    "    return response.json()\n\n"
    "# apm_connectors_mcp/server.py (this layer)\n"
    "async def _call(path: str, body: dict[str, Any]) -> Any:\n"
    "    try:\n"
    "        return await client.post(path, body)\n"
    "    except ConnectorAPIError as exc:\n"
    "        # ToolError is what MCP converts into a clean is_error result\n"
    "        # for the agent to see, rather than a raw/uncaught exception.\n"
    "        raise ToolError(str(exc)) from exc\n"
))
story.append(bl(
    "Four translation boundaries, four different exception types, each owned by the layer it protects: "
    "a raw Python exception inside a connector → HTTPException at the FastAPI boundary → "
    "ConnectorAPIError at the HTTP-client boundary → ToolError at the MCP boundary, which is what the "
    "<i>agent itself</i> ultimately sees as a clean is_error result — never a stack trace, never an "
    "unhandled crash, at any point in that chain. This is the pattern's fourth and final appearance, "
    "closing the loop from the deepest connector call all the way out to the LLM agent's own view of "
    "what happened."
))

# 8
story.append(h1("8. Pattern: action_status — read-only progress instead of a decision tool"))
story.append(bl(
    "An agent that proposed a write still needs to know what happened to it. Instead of a decision tool, "
    "it gets action_status, which reads two existing read-only routes and can't change anything:"
))
story.append(code_block(
    "@mcp.tool()\n"
    "async def action_status(action_id: str) -> dict[str, Any]:\n"
    '    """Read-only: the current status of a write proposed by\n'
    "    gmail_send, calendar_create_event, excel_write, drive_upload/\n"
    "    update, salesforce_create/update or jira_create/update ...\n"
    '    This tool cannot approve or reject anything."""\n'
    "    try:\n"
    '        pending = await client.get(f"/processes/{action_id}/pending")\n'
    "        if pending:\n"
    "            return {\n"
    '                "action_id": action_id,\n'
    '                "state": "awaiting_human_decision",\n'
    '                "pending": [{"tool": p.get("tool"), "description": p.get("description")} for p in pending],\n'
    "            }\n"
    '        status = await client.get(f"/processes/{action_id}/status")\n'
    "    except ConnectorAPIError as exc:\n"
    "        raise ToolError(str(exc)) from exc\n"
    '    return {"action_id": action_id, "state": status.get("stage"), "result": status.get("result")}\n'
))
story.append(bl(
    "Two details worth noticing. While a human hasn't decided yet, the state is the literal string "
    "awaiting_human_decision — the agent is told in plain words that the next move isn't its own. And the "
    "pending entries are trimmed to tool and description: the state store's own internal row id is dropped, "
    "so it can never be mistaken for the action_id (a mix-up that caused a real bug in the orchestrator "
    "repo)."
))
story.append(bl("The absence of a decision tool is tested, not just asserted — a regression guard that fails if one comes back:"))
story.append(code_block(
    "async def test_no_tool_can_decide_an_action(tmp_path: Path) -> None:\n"
    '    """Regression guard: the agent behind this MCP server must never be\n'
    "    able to approve or reject its own proposed writes. No tool may be\n"
    '    named like a decision, and none may reach the /decision route."""\n'
    "    mcp, *_ = _mcp(tmp_path)\n\n"
    "    names = {t.name for t in await mcp.list_tools()}\n"
    '    assert not {n for n in names if any(w in n for w in ("decide", "approve", "reject"))}\n\n'
    "    source = Path(build_server.__code__.co_filename).read_text()\n"
    '    code_only = "\\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))\n'
    '    assert \'"/tools/actions/\' not in code_only and "/decision\\"" not in code_only\n'
))
story.append(bl(
    "It checks two independent things: no tool <i>named</i> like a decision, and no code path in "
    "server.py that <i>reaches</i> the decision route under any name. A companion test, "
    "test_lists_one_tool_per_tools_route, pins the exact set of 22 tool names, so a new tool can't be added "
    "without someone looking at the list."
))

# 9
story.append(h1("9. Pattern: testing through the real protocol layer, over an in-process transport"))
story.append(bl(
    "This composes substitution tricks from <i>three different layers at once</i> — the most elaborate "
    "testing setup in the whole codebase:"
))
story.append(code_block(
    "def _mcp(tmp_path: Path, ...):\n"
    "    # 1. Connector layer: fake clients, no live credentials\n"
    '    tools = {"gmail": GmailTool(store, FakeGmailClient(...)), ...}\n'
    "    action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())\n\n"
    "    # 2. FastAPI layer: dependency_overrides swap in the fake-backed tools/graph\n"
    "    app = create_app()\n"
    "    app.dependency_overrides[get_tools] = lambda: tools\n"
    "    app.dependency_overrides[get_action_graph] = lambda: action_graph\n\n"
    "    # 3. This layer: ASGITransport swaps \"a real HTTP socket\" for\n"
    "    #    \"call straight into the ASGI app object in-process\"\n"
    '    client = ConnectorClient(base_url="http://testserver", transport=httpx.ASGITransport(app=app))\n'
    "    mcp = build_server(client)\n"
    "    return mcp, ...\n"
))
story.append(bl(
    "httpx.ASGITransport is the piece unique to this layer: normally, httpx.AsyncClient sends real "
    "bytes over a real socket to a real running server. Pass it an ASGITransport(app=app) instead, and "
    "every client.post(...) call — from ConnectorClient, unmodified — is routed directly into the "
    "FastAPI app object's ASGI interface in-process, no socket, no separately-running uvicorn, no "
    "network at all. Combined with dependency_overrides and MemorySaver(), the test exercises the "
    "<i>actual</i> MCP protocol layer, the <i>actual</i> FastAPI route handlers and Pydantic validation, "
    "and the <i>actual</i> graph.py propose/approve/execute pipeline — genuinely everything except a "
    "live socket and live third-party credentials. Three layers, three different substitution "
    "mechanisms (Depends() overrides, closures/factories, transport injection), the same underlying "
    "idea each time."
))
story.append(bl(
    "Since the MCP server has no way to approve anything, the tests that check a write really executes "
    "need a stand-in for the human. It talks to the REST API directly, never through an MCP tool:"
))
story.append(code_block(
    "async def _human_decides(app, action_id: str, approved: bool) -> dict:\n"
    '    """Stands in for the human-facing review surface: the decision goes\n'
    "    straight to the REST API, never through an MCP tool -- the agent\n"
    '    has no tool that can approve its own writes."""\n'
    '    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as human:\n'
    '        response = await human.post(f"/tools/actions/{action_id}/decision", json={"approved": approved})\n'
    "    assert response.status_code == 200, response.text\n"
    "    return response.json()\n"
))

# 10 walkthrough
story.append(h1("10. Walkthrough: one MCP tool call, traced across all five layers"))
story.append(bl(
    'gmail_send("customer@realcorp.io", "Update", "Your order shipped"), called by an LLM agent that '
    "decided this was the right tool for a user's request:"
))
trace = [
    ["1", "MCP", "The host serializes the call per the MCP protocol; build_server's registered gmail_send closure runs, calls _call(\"/tools/gmail/send\", {...})."],
    ["2", "MCP → HTTP", "ConnectorClient.post sends a real (or in-process, in tests) POST /tools/gmail/send."],
    ["3", "FastAPI", "gmail_send route: _tool(tools, \"gmail\") fail-fast check, then _propose() → start_action()."],
    ["4", "Action Graph", "propose_node records a pending action (State Store: add_pending_action, logs \"action_proposed\"); approval_node hits interrupt(), the graph pauses."],
    ["5", "FastAPI → MCP", "RunOutcomeResponse with pending_action set flows back as JSON; gmail_send hands it back as structured_content — action_id + pending_action visible to the agent, nothing sent."],
    ["6", "MCP (polling)", "The agent calls action_status(action_id): GET /processes/{id}/pending is non-empty, so it sees state=\"awaiting_human_decision\". It has no tool to change that."],
    ["7", "Human, outside MCP", "A person reviews the proposal on a human-facing review surface, which calls POST /tools/actions/{action_id}/decision with approved=true → resume_process() → Command(resume={\"approved\": True}) into the same graph thread."],
    ["8", "Action Graph", "approval_node replays, interrupt() returns immediately, State Store: resolve_pending_action logs \"action_approved\"; execute_node runs, decision=True → real branch: GmailTool.send_email(..., dry_run=False) fires — Connector Layer's placeholder-domain guard already passed, require_dry_run_guard logs \"action_executed\"."],
    ["9", "MCP (polling)", "The agent's next action_status(action_id) finds nothing pending, reads GET /processes/{id}/status, and sees state=\"done\" with result.executed = true."],
]
tw_rows = [[Paragraph(f"<b>{n}</b>", styles["tablecell"]), Paragraph(f"<b>{esc(l)}</b>", styles["tablecell"]), Paragraph(esc(t), styles["tablecell"])] for n, l, t in trace]
twt = Table(tw_rows, colWidths=[0.3 * inch, 0.95 * inch, USABLE_W - 1.25 * inch])
twt.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LINEBELOW", (0, 0), (-1, -2), 0.4, CODE_BORDER),
    ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
]))
story.append(twt)
story.append(bl("Nine steps, five layers, one gate (steps 4 and 8). Step 7 is the only one that can open it, and it's the only step that doesn't go through the MCP server."))

# 11 config
story.append(h1("11. Configuration and transport surface"))
story.append(code_block(
    'pip install -e ".[mcp]"\n'
    "APM_CONNECTORS_BASE_URL=http://127.0.0.1:8000 apm-connectors-mcp\n"
))
story.append(code_block(
    "def main() -> None:\n"
    "    client = ConnectorClient()\n"
    "    mcp = build_server(client)\n"
    '    transport = os.environ.get("APM_CONNECTORS_MCP_TRANSPORT", "stdio")\n'
    "    mcp.run(transport=transport)\n"
))
story.append(bl(
    "Three environment variables control everything: APM_CONNECTORS_BASE_URL (which /tools/* server to "
    "talk to — defaults to local), APM_CONNECTORS_API_KEY (the bearer token to send, only needed once that "
    "server has APM_API_KEYS set) and APM_CONNECTORS_MCP_TRANSPORT (stdio by default, matching a "
    "locally-configured agent host like Claude Desktop/Code; sse or streamable-http for a remote "
    "reasoning layer connecting over the network instead). No other configuration surface exists."
))

# 12 tool inventory
story.append(h1("12. Full tool inventory"))
tool_rows = [
    ["<b>MCP tool</b>", "<b>Kind</b>", "<b>REST route</b>"],
    ["gmail_search, gmail_read", "read", "POST /tools/gmail/{search,read}"],
    ["gmail_send", "write", "POST /tools/gmail/send"],
    ["calendar_search, calendar_read", "read", "POST /tools/calendar/{search,read}"],
    ["calendar_create_event", "write", "POST /tools/calendar/create-event"],
    ["excel_worksheets, excel_read", "read", "POST /tools/excel/{worksheets,read}"],
    ["excel_write", "write", "POST /tools/excel/write"],
    ["drive_list, drive_read", "read", "POST /tools/drive/{list,read}"],
    ["drive_upload, drive_update", "write", "POST /tools/drive/{upload,update}"],
    ["salesforce_query, salesforce_read", "read", "POST /tools/salesforce/{query,read}"],
    ["salesforce_create, salesforce_update", "write", "POST /tools/salesforce/{create,update}"],
    ["jira_search, jira_read", "read", "POST /tools/jira/{search,read}"],
    ["jira_create, jira_update", "write", "POST /tools/jira/{create,update}"],
    ["action_status", "read", "GET /processes/{id}/pending, then GET /processes/{id}/status"],
]
inv_rows = []
for i, r in enumerate(tool_rows):
    if i == 0:
        inv_rows.append([Paragraph(r[0], styles["tablehdr"]), Paragraph(r[1], styles["tablehdr"]), Paragraph(r[2], styles["tablehdr"])])
    else:
        color_hex = "#15803d" if r[1] == "read" else ("#b45309" if r[1] == "write" else "#1a1a2e")
        inv_rows.append([
            Paragraph(f"<font name='Courier'>{esc(r[0])}</font>", styles["tablecell"]),
            Paragraph(f"<font color='{color_hex}'><b>{esc(r[1])}</b></font>", styles["tablecell"]),
            Paragraph(f"<font name='Courier'>{esc(r[2])}</font>", styles["tablecell"]),
        ])
it = Table(inv_rows, colWidths=[2.6 * inch, 1.0 * inch, USABLE_W - 3.6 * inch])
it.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_FILL),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 4.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, CODE_BORDER),
    ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
]))
story.append(it)
story.append(bl(
    "22 tools: one per /tools/* data route, plus the read-only action_status. The one route deliberately "
    "<b>not</b> exposed is POST /tools/actions/{action_id}/decision — the same contract as the FastAPI "
    "reference's route table, minus the step that has to stay a human's."
))

# 13 vocab
story.append(h1("13. Vocabulary cheat-sheet"))
vocab = [
    ["MCP (Model Context Protocol)", "A standard for an LLM-based agent host to discover and call tools exposed by a separate server process."],
    ["Tool (MCP sense)", "A callable action with a typed schema and a description — both read by the LLM at call-decision time, not just by a human reading source."],
    ["Host", "The LLM-facing application (Claude Desktop, Claude Code, etc.) that connects to MCP servers and lets the model call their tools."],
    ["Transport", "How host and server communicate — stdio (local subprocess) or sse/streamable-http (network service)."],
    ["httpx.ASGITransport", "Routes an httpx client's calls directly into an ASGI app object in-process, no socket — the testing hook that lets this layer's tests exercise real FastAPI route handlers with no live server."],
    ["structured_content", "The typed result payload an MCP tool call returns to the calling agent."],
    ["ToolError / is_error", "MCP's mechanism for surfacing a failure to the agent as a clean, structured error result instead of a raw exception."],
    ["Approval boundary", "The rule that the caller who proposes a write can never be the one who approves it. Here: no MCP tool reaches the decision route; a human does, from outside."],
    ["action_status", "The agent's only window onto a proposed write's outcome — read-only, reporting awaiting_human_decision until a human decides."],
]
vocab_rows = [["<b>Term</b>", "<b>Meaning here</b>"]] + vocab
vt_rows = [[Paragraph(f"<font name='Courier'><b>{esc(r[0])}</b></font>" if i > 0 else r[0], styles["tablecell"]),
            Paragraph(esc(r[1]) if i > 0 else r[1], styles["tablecell"])]
           for i, r in enumerate(vocab_rows)]
vt = Table(vt_rows, colWidths=[1.9 * inch, USABLE_W - 1.9 * inch])
vt.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_FILL),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LINEBELOW", (0, 0), (-1, -1), 0.4, CODE_BORDER),
    ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
]))
story.append(vt)

story.append(Spacer(1, 10))
story.append(bl(
    "That's the whole layer — two small files, ~470 lines total — and it adds exactly one thing to "
    "everything covered before it: a natural-language-shaped front door for an LLM agent, sitting "
    "entirely outside the trust boundary, with zero new privilege and zero new enforcement code. The one "
    "guarantee that matters — a write cannot execute without a separate, later, human-approved call — "
    "already sits one layer down. This layer's only job is not to undermine it, which it does by never "
    "giving the agent a way to make that call itself."
))

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="MCP Server Layer -- apm_connectors_mcp/",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — MCP Server Reference")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
