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
     "Process status, the audit log, and pending (proposed-but-undecided) actions. Two interchangeable implementations behind one method surface (StateStoreProtocol) -- see the persistence table below."),
    ("HTTP API", "src/apm_connectors/api/",
     "app.py (FastAPI app + /health, /processes/*), tools_routes.py (one read/write route pair per connector), dependencies.py (builds the shared tools, state store, and compiled action graph once per process), schemas.py."),
    ("MCP server", "src/apm_connectors_mcp/",
     "Exposes every /tools/* route as an MCP tool for an LLM agent host (Claude Desktop/Code). Talks to the HTTP API purely over HTTP (client.py) -- never imports apm_connectors.tools/graph directly, so it deploys independently."),
    ("Config", "src/apm_connectors/config.py",
     "Reads environment variables into a Settings dataclass, including DATABASE_URL. No secrets ever live in this file -- see .env.example."),
    ("Deployment", "infra/aws/ecs-fargate/ (Terraform)",
     "Builds/pushes the image, stands up an ECS Fargate service behind a public ALB, stores OAuth/API secrets and DATABASE_URL as SSM SecureStrings. See docs/deployment.md."),
]
bottom1 = table(c, 40, PAGE_H - 105, sum(comp_cols), comp_cols,
                 ["Component", "Path", "Responsibility"], comp_rows, row_h=30, header_h=20)

# ---- Connector capability table ----------------------------------------
c.setFont("Helvetica-Bold", 12)
c.setFillColor(INK)
c.drawString(40, bottom1 - 24, "Connectors (5 live -- MS Graph/OneDrive Excel connector was removed)")

conn_cols = [140, 150, 180, 180, PAGE_W - 80 - 140 - 150 - 180 - 180]
conn_rows = [
    ("Gmail", "gmail_tool.py", "search, read", "send_email (action)", "Google OAuth 2.0 -- shared consent with Calendar"),
    ("Google Calendar", "calendar_tool.py", "search, read", "create_event (action)", "shared Google OAuth (same token as Gmail)"),
    ("Excel Files", "excel_file_tool.py", "read", "write_range", "Local disk, or Google Drive API"),
    ("Salesforce", "salesforce_tool.py", "SOQL query, read", "create, update", "OAuth 2.0 Client Credentials Flow"),
    ("Jira", "jira_tool.py", "JQL search, read", "create, update", "API token, Basic auth (jira_email + jira_api_token)"),
]
bottom2 = table(c, 40, bottom1 - 34, sum(conn_cols), conn_cols,
                 ["Connector", "Module", "Read capability", "Write/action capability", "Auth"], conn_rows,
                 row_h=18, header_h=18)

# ---- Persistence toggle table -------------------------------------------
c.setFont("Helvetica-Bold", 12)
c.setFillColor(INK)
c.drawString(40, bottom2 - 24, "Persistence -- pluggable behind one setting (DATABASE_URL)")

pers_cols = [190, (PAGE_W - 80 - 190) / 2, (PAGE_W - 80 - 190) / 2]
pers_rows = [
    ("State store", "StateStore -- local JSON file (state/store.py)", "PostgresStateStore -- Postgres tables, same method surface (state/postgres_store.py)"),
    ("LangGraph checkpointer", "MemorySaver -- in-process memory only", "PostgresSaver -- same Postgres database, same connection pool"),
    ("Survives a task replacement?", "No -- both vanish on restart, including anything mid-approval", "Yes -- live-verified: propose -> replace the ECS task -> pending action + audit trail intact -> approve -> executes"),
    ("Extra dependency", "none", "postgres extra (psycopg + psycopg_pool) -- installed unconditionally in the Docker image"),
    ("Connection resilience", "n/a", "check=ConnectionPool.check_connection replaces a dead pooled connection transparently (e.g. a serverless Postgres like Neon suspending idle compute)"),
]
bottom3 = table(c, 40, bottom2 - 34, sum(pers_cols), pers_cols,
                 ["", "No DATABASE_URL (default)", "DATABASE_URL set"], pers_rows, row_h=26, header_h=18)

# ---- Key invariants callout ---------------------------------------------
invariants = [
    "No write executes without an approved interrupt() resume -- enforced twice: graph.py's execute_node is the only place any tool's write/action method is ever called with dry_run=False, and every connector's own require_dry_run_guard refuses to treat a call as real without that flag. No config flag or \"autonomous mode\" bypasses this.",
    "This package has no reasoning of its own -- deciding what to read or write belongs to a separate reasoning/orchestration layer calling this API, not here.",
    "Adding a tool or a route is additive; changing an existing route's request/response shape is a breaking change for whatever's already coded against docs/api-contract.md.",
    "Every implementation swap (state store, checkpointer) happens behind an existing protocol/method surface, not by changing what callers depend on -- StateStoreProtocol is the example so far.",
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
