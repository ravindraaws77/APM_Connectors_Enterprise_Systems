"""Page 2 of docs/architecture.pdf: readable reference tables -- every
component, every connector, and the persistence pluggability toggle --
companion to gen_architecture_diagram.py's page 1 diagram. See
scripts/docs/README.md and gen_architecture_pdf.py (runs this, the
diagram, and the deep dive, then merges all three).

Run standalone with `python scripts/docs/gen_architecture_reference.py`;
writes scripts/docs/_build/architecture-reference.pdf by default
(override with the REFERENCE_OUT env var).
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import landscape, A3
from reportlab.pdfgen import canvas

from _canvas_template import GRAY, GREEN, GREEN_FILL, INK, PAGE_H, PAGE_W, table, wrap_text

OUT = Path(os.environ.get("REFERENCE_OUT", Path(__file__).resolve().parent / "_build" / "architecture-reference.pdf"))
OUT.parent.mkdir(parents=True, exist_ok=True)

c = canvas.Canvas(str(OUT), pagesize=landscape(A3))

c.setFillColor(INK)
c.setFont("Helvetica-Bold", 19)
c.drawString(40, PAGE_H - 42, "Component Reference")
c.setFont("Helvetica", 10.5)
c.setFillColor(GRAY)
c.drawString(40, PAGE_H - 60,
             "Every component from page 1, its path, and what it's responsible for -- plus the connector and persistence details that don't fit on the diagram.")

# ---- Components table -------------------------------------------------
c.setFont("Helvetica-Bold", 12)
c.setFillColor(INK)
c.drawString(40, PAGE_H - 95, "Components")

comp_cols = [150, 260, PAGE_W - 80 - 150 - 260]
comp_rows = [
    ("Tool connectors", "src/apm_connectors/tools/*.py",
     "One module per external system. Each implements the common BaseTool interface (tools/base.py): declares capabilities (read/write/action), and every write/action method takes dry_run and logs to the state store."),
    ("Action graph", "src/apm_connectors/graph.py",
     "A 3-node LangGraph (propose -> approval -> execute) that gates every write. approval_node's interrupt() is the actual mechanism -- the graph physically cannot proceed past it without a Command(resume=...) carrying a human decision."),
    ("State store", "src/apm_connectors/state/store.py, state/postgres_store.py",
     "Process status, the audit log (with proposed_by/decided_by), and pending actions. Postgres in production (postgres_store.py); the file-backed StateStore is a test double. Callers depend only on StateStoreProtocol."),
    ("HTTP API", "src/apm_connectors/api/",
     "app.py (FastAPI app, request log, /health, /metrics, /processes/*), tools_routes.py (read/write routes per connector + the one decision route), dependencies.py (shared tools/store/graph, Postgres required, require_caller auth), schemas.py."),
    ("MCP server", "src/apm_connectors_mcp/",
     "Exposes every /tools/* data route as an MCP tool, plus read-only action_status -- but deliberately NO tool for the decision route, so an agent can never approve its own writes. Pure HTTP client; deploys independently."),
    ("Config", "src/apm_connectors/config.py",
     "Reads environment variables into a Settings dataclass, including DATABASE_URL (required to run the server) and APM_API_KEYS (opt-in auth). No secrets ever live in this file -- see .env.example."),
    ("Deployment", "infra/aws/ecs-fargate/ (Terraform)",
     "Builds/pushes the image, stands up an ECS Fargate service behind a public ALB, stores OAuth/API secrets, DATABASE_URL and APM_API_KEYS as SSM SecureStrings. See docs/deployment.md."),
]
bottom1 = table(c, 40, PAGE_H - 105, sum(comp_cols), comp_cols,
                 ["Component", "Path", "Responsibility"], comp_rows, row_h=30, header_h=20)

# ---- Connector capability table ----------------------------------------
c.setFont("Helvetica-Bold", 12)
c.setFillColor(INK)
c.drawString(40, bottom1 - 24, "Connectors (6 live)")

conn_cols = [140, 150, 180, 180, PAGE_W - 80 - 140 - 150 - 180 - 180]
conn_rows = [
    ("Gmail", "gmail_tool.py", "search, read", "send_email (action)", "Google OAuth 2.0 -- shared consent with Calendar"),
    ("Google Calendar", "calendar_tool.py", "search, read", "create_event (action)", "shared Google OAuth (same token as Gmail)"),
    ("Excel Files", "excel_file_tool.py", "read", "write_range", "Local disk, or Google Drive API"),
    ("Google Drive", "drive_tool.py", "list, read (one folder)", "upload, update", "Google OAuth 2.0, full drive scope -- token shared with Excel-on-Drive"),
    ("Salesforce", "salesforce_tool.py", "SOQL query, read", "create, update", "OAuth 2.0 Client Credentials Flow"),
    ("Jira", "jira_tool.py", "JQL search, read", "create, update", "API token, Basic auth (jira_email + jira_api_token)"),
]
bottom2 = table(c, 40, bottom1 - 34, sum(conn_cols), conn_cols,
                 ["Connector", "Module", "Read capability", "Write/action capability", "Auth"], conn_rows,
                 row_h=18, header_h=18)

# ---- Persistence toggle table -------------------------------------------
c.setFont("Helvetica-Bold", 12)
c.setFillColor(INK)
c.drawString(40, bottom2 - 24, "Persistence -- Postgres is required to run the server (DATABASE_URL)")

pers_cols = [190, (PAGE_W - 80 - 190) / 2, (PAGE_W - 80 - 190) / 2]
pers_rows = [
    ("State store", "PostgresStateStore -- Postgres tables (state/postgres_store.py)", "StateStore -- local JSON file (state/store.py), a lightweight test double"),
    ("LangGraph checkpointer", "PostgresSaver -- same Postgres database, same connection pool", "MemorySaver -- in-process memory"),
    ("Survives a task replacement?", "Yes -- live-verified: propose -> replace the ECS task -> pending action + audit trail intact -> approve -> executes", "n/a"),
    ("Without DATABASE_URL", "The server refuses to start (_require_database_url); Terraform's validation fails plan", "Not needed: tests override get_state_store/get_action_graph"),
    ("Connection resilience", "check=ConnectionPool.check_connection replaces a dead pooled connection transparently (e.g. a serverless Postgres like Neon suspending idle compute)", "n/a"),
]
bottom3 = table(c, 40, bottom2 - 34, sum(pers_cols), pers_cols,
                 ["", "API server (production)", "Unit / integration tests"], pers_rows, row_h=26, header_h=18)

# ---- Key invariants callout ---------------------------------------------
invariants = [
    "No write executes without an approved interrupt() resume -- enforced twice: graph.py's execute_node is the only place any tool's write/action method is ever called with dry_run=False, and every connector's own require_dry_run_guard refuses to treat a call as real without that flag. No config flag or \"autonomous mode\" bypasses this.",
    "The caller that proposes a write can never approve it: the decision route is for a human through a review surface, and the MCP server exposes no tool for it (tests/test_mcp_server.py's test_no_tool_can_decide_an_action guards this).",
    "This package has no reasoning of its own -- deciding what to read or write belongs to a separate reasoning/orchestration layer calling this API, not here.",
    "Adding a tool or a route is additive; changing an existing route's request/response shape is a breaking change for whatever's already coded against docs/api-contract.md.",
    "Callers depend on a protocol/method surface, not an implementation -- StateStoreProtocol is why production runs on Postgres while tests use a file-backed double, with no route changes.",
]
INV_FONT_SIZE = 8.2
INV_LEADING = 11
INV_INDENT = 14
inv_max_w = (PAGE_W - 80) - (56 - 40) - 30 - INV_INDENT
wrapped_bullets = [wrap_text(c, text, "Helvetica", INV_FONT_SIZE, inv_max_w) for text in invariants]
inv_lines_total = sum(len(wl) for wl in wrapped_bullets)
inv_y = bottom3 - 20
inv_h = 34 + inv_lines_total * INV_LEADING + 8

c.saveState()
c.setStrokeColor(GREEN)
c.setFillColor(GREEN_FILL)
c.setLineWidth(1.2)
c.roundRect(40, inv_y - inv_h, PAGE_W - 80, inv_h, 8, fill=1, stroke=1)
c.setFont("Helvetica-Bold", 10.5)
c.setFillColor(GREEN)
c.drawString(56, inv_y - 18, "Key invariants worth remembering")
c.setFont("Helvetica", INV_FONT_SIZE)
c.setFillColor(INK)
iy = inv_y - 34
for wl in wrapped_bullets:
    c.drawString(56, iy, "•")
    for j, ln in enumerate(wl):
        c.drawString(56 + INV_INDENT, iy, ln)
        iy -= INV_LEADING
c.restoreState()

c.showPage()
c.save()
print("wrote", OUT)
