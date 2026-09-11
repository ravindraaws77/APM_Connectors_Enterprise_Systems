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
story.append(caption("A minimal MCP tool — the pattern this file repeats eighteen times"))
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
    "ConnectorClient (client.py) is genuinely minimal — one constructor, one post method, ~35 lines of "
    "real logic. It has no knowledge of GmailTool, BaseTool, graph.py, or StateStore. Every one of the "
    "other five layers this document set has covered is, from this package's point of view, just "
    "“whatever's running behind APM_CONNECTORS_BASE_URL.” This is the same “depend on the API contract, "
    "not the implementation” discipline the State Store reference called a <i>migration seam</i> — here "
    "it's drawn at a much bigger scale: not just swappable storage, but a swappable, "
    "independently-deployable <i>process</i>."
))
story.append(code_block(
    "class ConnectorClient:\n"
    "    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:\n"
    "        self._client = httpx.AsyncClient(\n"
    '            base_url=base_url or os.environ.get("APM_CONNECTORS_BASE_URL", DEFAULT_BASE_URL),\n'
    "            timeout=30.0,\n"
    "            transport=transport,\n"
    "        )\n"
))
story.append(bl(
    "Two configuration surfaces worth naming: base_url defaults to APM_CONNECTORS_BASE_URL, falling "
    "back to 127.0.0.1:8000 (the same default docs/running-locally.md uses) — so a locally-run MCP "
    "server talks to a locally-run API server with zero configuration, but pointing it at a remote "
    "deployment (say, the ECS Fargate service_url from the Terraform reference) is a single environment "
    "variable, no code change. transport is the testing hook — covered fully in §9."
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
    "almost verbatim (“This does NOT send anything — it pauses for human approval”) rather than relying "
    "on a shared reference: an LLM reads <i>this</i> tool's description in isolation when deciding how "
    "to act, so the safety-relevant fact has to be restated locally, every time."
))

# 6
story.append(h1("6. Pattern: the approval gate, re-verified from the outside"))
story.append(quote_block(
    "“Every write tool... mirrors the REST API exactly: it does not execute anything — it returns a "
    "paused action_id, and the agent must call decide_action(action_id, approved=True) to actually run "
    "it. That gate is enforced server-side in the /tools/* API regardless of what this MCP layer does, "
    "so it can't be bypassed by a misbehaving or adversarial agent — this module is a "
    "description/transport convenience on top of it, not a second copy of the guardrail.”"
))
story.append(bl("Look at what gmail_send actually does here:"))
story.append(code_block(
    "@mcp.tool()\n"
    "async def gmail_send(to: str, subject: str, body: str, process_id: str | None = None) -> dict[str, Any]:\n"
    '    """Propose sending a Gmail email. This does NOT send anything..."""\n'
    '    return await _call("/tools/gmail/send", {"to": to, "subject": subject, "body": body, "process_id": process_id})\n'
))
story.append(bl(
    "It's an HTTP POST to /tools/gmail/send — the exact same route covered in the FastAPI reference, "
    "hitting the exact same _propose() → start_action() → propose_node → approval_node[interrupt()] "
    "pipeline covered in the Action Graph reference. <b>This layer adds no new enforcement, and needs "
    "none.</b> An “adversarial agent” — one that hallucinates, or is deliberately prompted to try to "
    "send an email without approval — has no more power here than a malicious script hitting the REST "
    "API directly, because both go through the identical server-side gate. Nothing about exposing these "
    "as MCP tools required re-deriving or re-implementing that guarantee."
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
story.append(h1("8. Pattern: decide_action — the MCP-layer twin of the one shared decision route"))
story.append(code_block(
    "@mcp.tool()\n"
    "async def decide_action(action_id: str, approved: bool) -> dict[str, Any]:\n"
    '    """Approve or reject a pending write proposed by gmail_send,\n'
    "    calendar_create_event, excel_write, salesforce_create/update, or\n"
    "    jira_create/update (its action_id from that call's response).\n"
    "    Nothing in the real system happens until this is called with\n"
    "    approved=true; approved=false discards it -- nothing is\n"
    '    sent/created/written either way.\n'
    '    """\n'
    '    return await _call(f"/tools/actions/{action_id}/decision", {"approved": approved})\n'
))
story.append(bl(
    "Exactly one decide_action tool, same as exactly one shared POST /tools/actions/{action_id}/decision "
    "route in tools_routes.py — this layer really is a mechanical, one-tool-per-route mirror of the "
    "REST contract, and that claim is directly tested, not just asserted:"
))
story.append(code_block(
    "async def test_lists_one_tool_per_tools_route(tmp_path: Path) -> None:\n"
    "    mcp, *_ = _mcp(tmp_path)\n"
    "    tools = await mcp.list_tools()\n"
    "    names = {t.name for t in tools}\n"
    '    assert names == {"gmail_search", "gmail_read", "gmail_send", ..., "decide_action"}\n'
))
story.append(bl("Eighteen tools, one call to mcp.list_tools(), compared against the exact expected set — the clearest possible proof that this layer adds no hidden capabilities and drops none."))

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
    ["6", "MCP (later)", "Agent (or the human behind it) calls decide_action(action_id, approved=True)."],
    ["7", "FastAPI", "decide_action route → resume_process() → Command(resume={\"approved\": True}) into the same cached graph thread."],
    ["8", "Action Graph", "approval_node replays, interrupt() returns immediately, State Store: resolve_pending_action logs \"action_approved\"; execute_node runs, decision=True → real branch: GmailTool.send_email(..., dry_run=False) fires — Connector Layer's placeholder-domain guard already passed, require_dry_run_guard logs \"action_executed\"."],
    ["9", "All the way back", "final_result with executed: true flows back through FastAPI → ConnectorClient → decide_action's return value → the agent sees the email was actually sent."],
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
story.append(bl("Nine steps, five layers, one gate (step 4/8) that nothing in this chain has the power to skip."))

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
    "Two environment variables control everything: APM_CONNECTORS_BASE_URL (which /tools/* server to "
    "talk to — defaults to local) and APM_CONNECTORS_MCP_TRANSPORT (stdio by default, matching a "
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
    ["salesforce_query, salesforce_read", "read", "POST /tools/salesforce/{query,read}"],
    ["salesforce_create, salesforce_update", "write", "POST /tools/salesforce/{create,update}"],
    ["jira_search, jira_read", "read", "POST /tools/jira/{search,read}"],
    ["jira_create, jira_update", "write", "POST /tools/jira/{create,update}"],
    ["decide_action", "shared decision", "POST /tools/actions/{action_id}/decision"],
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
story.append(bl("18 tools, exactly mirroring the FastAPI reference's route table — this is the same contract, in a different vocabulary, for a different kind of caller."))

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
    "That's the whole layer — two small files, ~380 lines total — and it adds exactly one thing to "
    "everything covered before it: a natural-language-shaped front door for an LLM agent, sitting "
    "entirely outside the trust boundary, with zero new privilege and zero new enforcement code, "
    "because the one guarantee that matters — a write cannot execute without a separate, later, "
    "human-approved call — was already sitting one layer down, and works identically no matter what's "
    "calling it."
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
