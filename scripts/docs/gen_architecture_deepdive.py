# -*- coding: utf-8 -*-
"""Pages 3+ of docs/architecture.pdf: a concise deep dive -- request
flow, the connector interface, the approval gate, the pluggable
persistence layer, the MCP front door, and deployment. One focused
section per layer, not an exhaustive per-layer reference (those exist
as separate docs -- see scripts/docs/README.md). Companion to
gen_architecture_diagram.py + gen_architecture_reference.py; run all
three and merge them via gen_architecture_pdf.py.

Run standalone with `python scripts/docs/gen_architecture_deepdive.py`;
writes scripts/docs/_build/architecture-deepdive.pdf by default
(override with the DEEPDIVE_OUT env var).
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from _pdf_template import (
    CODE_BORDER, GRAY_FILL, MARGIN, USABLE_W,
    bl, esc, footer, h1, quote_block, rule, simple_table, styles, code_block as _code_block,
)

OUT = Path(os.environ.get("DEEPDIVE_OUT", Path(__file__).resolve().parent / "_build" / "architecture-deepdive.pdf"))
OUT.parent.mkdir(parents=True, exist_ok=True)

story = []

# ---------------------------------------------------------------------------
story.append(Paragraph("Deep Dive — Request Flow, Connectors, Persistence, MCP, Deployment", styles["title"]))
story.append(Paragraph(
    "The mechanics behind pages 1-2's diagram and tables, in reading order: how a call actually "
    "moves through the system, the connector interface every tool implements, the pluggable "
    "persistence layer behind the approval gate, the MCP front door, and how it all deploys.",
    styles["subtitle"],
))
story.append(rule())

# 1 -- request flow
story.append(h1("1. How a call moves through the system"))
story.append(bl(
    "Every /tools/* route follows one of exactly two shapes, and nothing in this codebase deviates "
    "from them. <b>A read executes immediately</b> -- no approval, no graph involved:"
))
story.append(_code_block(
    "@router.post(\"/salesforce/query\")\n"
    "def salesforce_query(body: SalesforceQueryRequest, tools=Depends(get_tools)) -> list[dict]:\n"
    "    tool = _tool(tools, \"salesforce\")\n"
    "    results = tool.query_records(process_id, soql=body.soql)\n"
    "    return [r.__dict__ for r in results]\n"
))
story.append(bl(
    "<b>A write never executes on the call that proposes it.</b> The route never calls the tool's "
    "write method directly -- it calls start_action, which hands the request to the action graph:"
))
story.append(_code_block(
    "@router.post(\"/salesforce/create\", response_model=RunOutcomeResponse)\n"
    "def salesforce_create(body: SalesforceCreateRequest, tools=Depends(get_tools), graph=Depends(get_action_graph)):\n"
    "    _tool(tools, \"salesforce\")  # fail fast, before recording a pending action doomed to fail\n"
    "    description = f\"Create Salesforce {body.object_name} record\"\n"
    "    payload = {\"object_name\": body.object_name, \"fields\": body.fields}\n"
    "    return _propose(graph, action_id, \"salesforce\", \"create_record\", description, payload)\n"
    "\n"
    "@router.post(\"/actions/{action_id}/decision\", response_model=RunOutcomeResponse)\n"
    "def decide_action(action_id: str, body: DecisionRequest, graph=Depends(get_action_graph)):\n"
    "    outcome = resume_process(graph, action_id, approved=body.approved)\n"
    "    return to_response(outcome)\n"
))
story.append(bl(
    "Every one of the five connectors' write/action routes (gmail_send, calendar_create_event, "
    "excel_write, salesforce_create/update, jira_create/update) is the same three lines: look up the "
    "tool to fail fast on an unconfigured connector, build a description + payload, call _propose. "
    "There is exactly <b>one</b> decision route -- /tools/actions/{action_id}/decision -- shared by "
    "all of them, because approving or rejecting is the same operation regardless of which connector "
    "proposed the action."
))

# 2 -- connector layer
story.append(h1("2. The connector layer — one interface, five connectors"))
story.append(bl(
    "Every connector (gmail_tool.py, calendar_tool.py, excel_file_tool.py, salesforce_tool.py, "
    "jira_tool.py) implements the same abstract base:"
))
story.append(_code_block(
    "class Capability(str, Enum):\n"
    "    READ = \"read\"\n"
    "    WRITE = \"write\"\n"
    "    ACTION = \"action\"\n"
    "\n"
    "@dataclass(frozen=True)\n"
    "class ActionResult:\n"
    "    executed: bool\n"
    "    description: str\n"
    "    details: dict[str, Any]\n"
    "\n"
    "class BaseTool(ABC):\n"
    "    name: str\n"
    "    capabilities: frozenset[Capability]\n"
    "\n"
    "    def require_dry_run_guard(self, dry_run: bool, process_id: str, summary: str) -> None:\n"
    "        \"\"\"Defense in depth alongside the graph's interrupt() gate -- logs\n"
    "        action_executed for a real call, action_proposed for a dry run.\"\"\"\n"
    "        event_type = \"action_executed\" if not dry_run else \"action_proposed\"\n"
    "        self._log(process_id, event_type, summary, {\"dry_run\": dry_run})\n"
))
story.append(bl(
    "Two things worth noticing. First, <b>require_dry_run_guard is not the approval gate</b> -- the "
    "graph's interrupt() (section 3) is what actually prevents a write from running. This guard is a "
    "second, independent check inside the connector itself: even if something upstream of the "
    "connector were ever wired incorrectly, no write method can silently skip logging what it did. "
    "Second, <b>ActionResult.executed</b> is the one field every caller checks to tell a real write "
    "from a dry run or a rejection -- the shape is identical either way, so nothing downstream needs "
    "a special case for \"this didn't actually happen.\""
))
story.append(bl(
    "The MS Graph/OneDrive Excel connector that originally existed alongside excel_file_tool.py has "
    "been removed entirely (code, tests, docs, Terraform) in favor of the local-file/Google-Drive "
    "Excel connector alone — one Excel implementation, not two competing ones."
))

# 3 -- approval gate
story.append(h1("3. The approval gate — propose, interrupt, resume"))
story.append(bl(
    "graph.py compiles a 3-node LangGraph: propose -> approval -> execute. The middle node is the "
    "entire guarantee this package exists to provide:"
))
story.append(_code_block(
    "def approval_node(state: GraphState) -> dict[str, Any]:\n"
    "    decision = interrupt({\n"
    "        \"type\": \"approval_request\", \"action_id\": action_id, \"tool\": proposed[\"tool\"],\n"
    "        \"method\": proposed[\"method\"], \"description\": proposed[\"description\"],\n"
    "        \"payload\": proposed[\"payload\"], \"category\": state.get(\"category\", \"other\"),\n"
    "    })\n"
    "    approved = bool(decision.get(\"approved\")) if isinstance(decision, dict) else bool(decision)\n"
    "    state_store.resolve_pending_action(action_id, approved=approved)\n"
    "    return {\"decision\": approved}\n"
))
story.append(bl(
    "interrupt() physically stops execution at that line -- the graph cannot proceed to execute_node "
    "without a Command(resume=...) carrying a human decision, delivered via the shared decision route. "
    "On resume, LangGraph <i>replays</i> approval_node from the top; interrupt() is deliberately the "
    "first side-effecting statement in the function so replay is harmless, and resolve_pending_action "
    "runs exactly once, on the resume pass, after interrupt() returns. execute_node is the only place "
    "in the entire codebase where a tool's write/action method is ever called with dry_run=False. "
    "Rejecting instead of approving skips that call entirely -- nothing is ever sent, created, or "
    "written on a rejection."
))

# 4 -- persistence (the newest, most important addition)
story.append(h1("4. Persistence — the pluggable state store and checkpointer"))
story.append(bl(
    "Two different things need to survive between a write being proposed and a human deciding on it, "
    "and until recently neither one reliably did on this deployment's actual infrastructure (AWS ECS "
    "Fargate tasks have no persistent disk, and a redeploy replaces the running task entirely):"
))
story.append(simple_table(
    [
        ["<b></b>", "<b>No DATABASE_URL (default)</b>", "<b>DATABASE_URL set</b>"],
        ["State store<br/>(status, audit log, pending actions)",
         "StateStore — a local JSON file (state/store.py)",
         "PostgresStateStore — Postgres tables, identical method surface (state/postgres_store.py)"],
        ["LangGraph checkpointer<br/>(the graph's own paused execution state)",
         "MemorySaver — in-process memory only, gone the instant the process dies",
         "PostgresSaver (langgraph-checkpoint-postgres) — same Postgres database"],
    ],
    [1.9 * inch, (USABLE_W - 1.9 * inch) / 2, (USABLE_W - 1.9 * inch) / 2],
))
story.append(bl(
    "Both are picked by the exact same signal, in api/dependencies.py, and share one connection pool "
    "rather than opening two separate sets of connections to the same database:"
))
story.append(_code_block(
    "@lru_cache\n"
    "def get_state_store() -> StateStoreProtocol:\n"
    "    settings = load_settings()\n"
    "    if settings.database_url:\n"
    "        from apm_connectors.state.postgres_store import PostgresStateStore\n"
    "        return PostgresStateStore(_get_postgres_pool())\n"
    "    return StateStore()\n"
    "\n"
    "@lru_cache\n"
    "def get_action_graph():\n"
    "    if settings.database_url:\n"
    "        from langgraph.checkpoint.postgres import PostgresSaver\n"
    "        checkpointer = PostgresSaver(_get_postgres_pool())\n"
    "        checkpointer.setup()\n"
    "    else:\n"
    "        checkpointer = MemorySaver()\n"
    "    return build_action_graph(get_tools(), get_state_store(), checkpointer=checkpointer)\n"
))
story.append(bl(
    "Callers (tools, routes, tests) only ever depend on <b>StateStoreProtocol</b>'s method surface, "
    "never on which class is behind it — that's what made this swap possible without touching "
    "anything outside state/ and api/dependencies.py. One more detail worth knowing: the pool is "
    "opened with check=ConnectionPool.check_connection, which verifies a connection is actually alive "
    "before handing it out and transparently replaces it if not. Without this, a serverless Postgres "
    "provider (Neon, etc.) suspending its compute while a pooled connection sits idle breaks every "
    "call using it indefinitely with \"SSL connection has been closed unexpectedly\" — live-verified "
    "against Neon, and the fix that made it reliable."
))
story.append(quote_block(
    "Live-verified end to end: propose a write → replace the ECS task entirely → the pending action "
    "and its audit trail are still there on the brand-new task → approve → it executes. That's the "
    "actual scenario a real deployment needs to survive, not just \"the server didn't crash.\""
))

# 5 -- MCP
story.append(h1("5. The MCP server — the natural-language front door"))
story.append(bl(
    "src/apm_connectors_mcp/ is a separate top-level package (its own pyproject.toml extra, own "
    "console-script entry point) that exposes every /tools/* route as an MCP tool for an LLM agent "
    "host such as Claude Desktop or Claude Code. It talks to the HTTP API purely over httpx -- it "
    "never imports apm_connectors.tools or apm_connectors.graph directly -- so it adds no new "
    "enforcement code and needs none: an MCP tool call to gmail_send still ends up as a plain "
    "POST /tools/gmail/send, hitting the exact same start_action → interrupt() → approval pipeline "
    "as any other caller. A misbehaving or adversarial agent has no more power here than a script "
    "hitting the REST API directly."
))
story.append(bl(
    "Eighteen tools in total mirror the eighteen /tools/* routes one-to-one, plus a single shared "
    "decide_action tool for the decision route. Tool docstrings here do real work beyond documenting "
    "for a human reader — they're the natural-language interface an LLM reads at call-decision time "
    "to translate a free-text request into an actual call with the right arguments."
))

# 6 -- deployment
story.append(h1("6. Deployment — AWS ECS on Fargate"))
story.append(bl(
    "infra/aws/ecs-fargate/ (Terraform) builds and pushes the image, then stands up an ECS Fargate "
    "service behind a public Application Load Balancer that health-checks /health, in the account's "
    "default VPC. terraform apply does the whole thing in one command — including the docker build/"
    "push itself, via a local-exec provisioner — no separate CI/CD system. Every connector credential "
    "and DATABASE_URL are optional Terraform variables, defaulting to empty exactly like an unfilled "
    "local .env; secrets are stored as SSM SecureString parameters, never plain environment variables, "
    "and resolved by ECS at task startup."
))
story.append(bl(
    "Two things Terraform's own diff genuinely cannot see, both compensated for by a null_resource "
    "that hashes the actual content and forces a fresh deployment when it changes: a new image pushed "
    "to the same :latest tag (the task definition's image string is unchanged either way), and an SSM "
    "secret's value rotating in place (its ARN — all the task definition's secrets block ever "
    "references — doesn't change, and ECS only resolves secrets once, at task startup)."
))
story.append(bl(
    "The Postgres instance itself is provisioned separately (RDS, or an external managed Postgres "
    "such as Neon) and wired in with a single database_url Terraform variable, stored the same "
    "SSM-SecureString way as every other secret — Terraform doesn't stand up the database, only "
    "points the running task at it."
))

# 7 -- vocab
story.append(h1("7. Vocabulary cheat-sheet"))
vocab = [
    ["BaseTool / Capability", "The common connector interface (tools/base.py) and its read/write/action capability flags."],
    ["dry_run guard", "require_dry_run_guard — a connector-level defense in depth that logs every real vs. dry-run call, independent of the graph's interrupt() gate."],
    ["interrupt() / Command(resume=...)", "LangGraph's pause/resume primitive — the actual mechanism that makes a write physically wait for a human decision."],
    ["Checkpointer", "Where a paused graph's execution state lives between the pause and the resume — MemorySaver (in-process) or PostgresSaver (durable)."],
    ["StateStoreProtocol", "The method surface every state store implementation (file-backed or Postgres) satisfies — what callers actually depend on."],
    ["DATABASE_URL", "The single setting that switches both the state store and the checkpointer from in-memory/local-file to Postgres, together."],
    ["MCP (Model Context Protocol)", "The standard this package's separate apm_connectors_mcp package uses to expose /tools/* as tools for an LLM agent host."],
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
    "That's the whole system: a thin, reasoning-free HTTP layer over five connectors, gated by one "
    "interrupt-based approval mechanism, backed by a persistence layer that can be either "
    "zero-infrastructure or durable behind a single setting, reachable by a script, a reasoning layer, "
    "or an LLM agent through the same contract either way."
))

doc = SimpleDocTemplate(
    str(OUT), pagesize=letter,
    leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=0.95 * inch,
    title="APM Connectors -- Architecture Deep Dive",
)
DOC_FOOTER = footer("APM Connectors & Enterprise Systems — Architecture Deep Dive")
doc.build(story, onFirstPage=DOC_FOOTER, onLaterPages=DOC_FOOTER)
print("wrote", OUT)
