"""Page 1 of docs/architecture.pdf: the whole-system diagram (every
component, the propose/approve/execute loop, the pluggable persistence
layer, all five connectors) as one landscape-A3 flowchart. See
scripts/docs/README.md for the overall doc shape and
gen_architecture_pdf.py for the script that runs this, its companion
page, and the deep dive, then merges all three.

Run standalone with `python scripts/docs/gen_architecture_diagram.py`;
writes scripts/docs/_build/architecture-diagram.pdf by default
(override with the DIAGRAM_OUT env var).
"""

import os
from pathlib import Path

from reportlab.lib.pagesizes import landscape, A3
from reportlab.pdfgen import canvas

from _canvas_template import (
    AMBER, AMBER_FILL, BLUE, BLUE_FILL, GRAY, GRAY_FILL, GREEN, GREEN_FILL, INK,
    PAGE_H, PAGE_W, RED, WHITE, arrow, box, container, poly_arrow,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("DIAGRAM_OUT", Path(__file__).resolve().parent / "_build" / "architecture-diagram.pdf"))
OUT.parent.mkdir(parents=True, exist_ok=True)

c = canvas.Canvas(str(OUT), pagesize=landscape(A3))

# ---- Title ----------------------------------------------------------------
c.setFillColor(INK)
c.setFont("Helvetica-Bold", 19)
c.drawString(40, PAGE_H - 42, "APM Connectors & Enterprise Systems — Architecture")
c.setFont("Helvetica", 10.5)
c.setFillColor(GRAY)
c.drawString(40, PAGE_H - 60,
             "Connector / enterprise-systems layer only — no reasoning, no LLM call, no free-text entry point in this process (docs/api-contract.md)")
c.setFont("Helvetica-Oblique", 8.4)
c.setFillColor(BLUE)
c.drawString(40, PAGE_H - 74,
             "Updated: 5 live connectors (MS Graph Excel removed), Postgres-backed state store + LangGraph checkpointer (DATABASE_URL), MCP server layer")

# ---- Row 1: external callers ----------------------------------------------
top_y = PAGE_H - 130
callers_h = 46
box(c, 40, top_y, 300, callers_h,
    ["Reasoning / Orchestration Layer", "separate deployment — decides what to read / what write to propose"],
    fill=GRAY_FILL, stroke=GRAY, text_color=INK)

box(c, PAGE_W - 340, top_y, 300, callers_h,
    ["LLM Agent", "Claude Desktop / Claude Code / any MCP-capable host"],
    fill=GRAY_FILL, stroke=GRAY, text_color=INK)

mcp_y = top_y - 76
box(c, PAGE_W - 340, mcp_y, 300, 46,
    ["apm_connectors_mcp", "MCP server (stdio / SSE / streamable-http) — same /tools/* routes as MCP tools"],
    fill=GRAY_FILL, stroke=GRAY, text_color=INK)

arrow(c, PAGE_W - 190, top_y, PAGE_W - 190, mcp_y + 46, color=INK)

# ---- Row 2: FastAPI container ----------------------------------------------
api_y = mcp_y - 96
api_h = 74
container(c, 40, api_y, PAGE_W - 80, api_h,
          "APM Connectors API  —  FastAPI (uvicorn apm_connectors.api.app:app)",
          stroke=BLUE, fill=BLUE_FILL, title_color=BLUE)

box(c, 70, api_y + 12, 420, 34,
    ["/tools/* routes", "tools_routes.py — per-tool read + write endpoints, no reasoning"],
    fill=WHITE, stroke=BLUE, text_color=INK, title_size=9, body_size=7.4)
box(c, PAGE_W - 490, api_y + 12, 420, 34,
    ["/health, /processes/*", "app.py — status, audit history, pending actions"],
    fill=WHITE, stroke=BLUE, text_color=INK, title_size=9, body_size=7.4)

arrow(c, 190, top_y, 190, api_y + api_h, label="HTTP  POST /tools/*")
arrow(c, PAGE_W - 190, mcp_y, PAGE_W - 190, api_y + api_h, label="HTTP  (same /tools/* contract)")

# ---- Row 3: action graph + human approver ----------------------------------
graph_y = api_y - 120
graph_h = 96
graph_x, graph_w = 40, PAGE_W - 300
container(c, graph_x, graph_y, graph_w, graph_h,
          "Action Graph  —  graph.py (build_action_graph, LangGraph)",
          stroke=AMBER, fill=AMBER_FILL, title_color=AMBER)

node_y = graph_y + 14
node_h = 40
node_top = node_y + node_h
propose_x, propose_w = graph_x + 20, 180
approval_x, approval_w = propose_x + propose_w + 60, 260
execute_x, execute_w = approval_x + approval_w + 60, 200

box(c, propose_x, node_y, propose_w, node_h,
    ["propose_node", "records pending action"], fill=WHITE, stroke=AMBER, title_size=9, body_size=7.4)
box(c, approval_x, node_y, approval_w, node_h,
    ["approval_node", "interrupt() — pauses until a human decides"], fill=WHITE, stroke=RED, text_color=INK,
    title_size=9, body_size=7.4)
box(c, execute_x, node_y, execute_w, node_h,
    ["execute_node", "only place dry_run=False is ever called"], fill=WHITE, stroke=AMBER, title_size=9, body_size=7.4)

arrow(c, propose_x + propose_w, node_y + node_h / 2, approval_x, node_y + node_h / 2, color=AMBER)
arrow(c, approval_x + approval_w, node_y + node_h / 2, execute_x, node_y + node_h / 2, color=AMBER)

arrow(c, 190, api_y, 190, graph_y + graph_h, label="start_action() / resume_process()")

# Human approver
human_x, human_w = graph_x + graph_w + 40, 220
human_y = graph_y
box(c, human_x, human_y, human_w, graph_h,
    ["Human Approver", "sees pending_action (tool, method, description, payload)",
     "POST /tools/actions/{action_id}/decision"],
    fill=WHITE, stroke=RED, text_color=INK, title_size=9.5, body_size=7.2)

approval_cx = approval_x + approval_w / 2

# Route both approval<->human links OVER the top of execute_node (never
# through its box) via a shared overpass band inside the container's
# top margin (node_top .. graph_y+graph_h has ~42pt of clear space).
overpass_out = node_top + 8   # approval_node -> human (pending_action)
overpass_in = node_top + 22   # human -> approval_node (decision)

poly_arrow(
    c,
    [(approval_x + approval_w - 30, node_top), (approval_x + approval_w - 30, overpass_out),
     (human_x + 55, overpass_out), (human_x + 55, human_y + graph_h)],
    color=RED, label="pending_action",
)
poly_arrow(
    c,
    [(human_x + 150, human_y + graph_h), (human_x + 150, overpass_in),
     (approval_x + approval_w - 90, overpass_in), (approval_x + approval_w - 90, node_top)],
    color=GREEN, label="{approved: true/false}",
)

# ---- Row 4: connector layer -------------------------------------------------
conn_y = graph_y - 96
conn_h = 60
container(c, 40, conn_y, PAGE_W - 80, conn_h,
          "Connector Layer  —  tools/base.BaseTool  (capabilities: read / write / action, dry_run guard, audit log)",
          stroke=BLUE, fill=BLUE_FILL, title_color=BLUE)

connectors = [
    ("Gmail", "gmail_tool.py", "search / read → send_email (action)"),
    ("Google Calendar", "calendar_tool.py", "search / read → create_event (action)"),
    ("Excel Files", "excel_file_tool.py", "local + Google Drive → write_range"),
    ("Salesforce", "salesforce_tool.py", "SOQL query / read → create/update"),
    ("Jira", "jira_tool.py", "JQL search / read → create/update"),
]
n = len(connectors)
gap = 16
cw = (PAGE_W - 80 - 20 * 2 - gap * (n - 1)) / n
cx0 = 60
conn_boxes = []
for i, (name, mod, cap) in enumerate(connectors):
    cx = cx0 + i * (cw + gap)
    cy = conn_y + 10
    box(c, cx, cy, cw, 36, [name, mod, cap], fill=WHITE, stroke=BLUE, title_size=8.6, body_size=6.6)
    conn_boxes.append((cx + cw / 2, cy))

arrow(c, graph_x + graph_w / 2, graph_y, graph_x + graph_w / 2, conn_y + conn_h,
      label="method(process_id, dry_run=False)")

# ---- Row 5: external systems ------------------------------------------------
ext_y = conn_y - 74
ext_h = 50
externals = [
    "Gmail API\n(Google OAuth 2.0)",
    "Google Calendar API\n(shared Google OAuth)",
    "Local disk /\nGoogle Drive API",
    "Salesforce REST API\n(Client Credentials Flow)",
    "Jira Cloud REST API\n(API token, Basic auth)",
]
for i, label in enumerate(externals):
    cx = cx0 + i * (cw + gap)
    lines = label.split("\n")
    box(c, cx, ext_y, cw, ext_h, lines, fill=GRAY_FILL, stroke=GRAY, title_size=8.2, body_size=7.2,
        title_font="Helvetica-Bold")
    bx, by = conn_boxes[i]
    arrow(c, bx, by, cx + cw / 2, ext_y + ext_h, color=GRAY)

# ---- State store (spans everything, dashed audit arrows) -------------------
store_y = 40
store_h = 56
container(c, 40, store_y, graph_x + graph_w - 40, store_h,
          "Persistence Layer  —  State Store + LangGraph Checkpointer  (pluggable via DATABASE_URL)", stroke=GREEN, fill=GREEN_FILL, title_color=GREEN)
c.setFont("Helvetica", 7.6)
c.setFillColor(INK)
c.drawString(60, store_y + 20,
             "No DATABASE_URL (default): StateStore JSON file + in-process MemorySaver — zero infra, lost on restart. DATABASE_URL set: PostgresStateStore + PostgresSaver, one shared connection pool — survives a redeploy/task replacement.")
c.drawString(60, store_y + 8, "Same method surface either way (StateStoreProtocol) — status, audit events (proposed/approved/rejected/executed/failed), and pending_actions. Every read and write is logged here.")

store_top_cx = 40 + (graph_x + graph_w - 40) / 2

# Clear vertical corridors: the 4 inter-column gaps line up identically
# between the connector row and the external-systems row below it (same
# cx0/cw/gap), so a line centered on one of those gaps clears every box
# in both rows for its whole vertical run. Below the external row is
# open whitespace down to the state store, where the line can angle in.
gap_x = [cx0 + (i + 1) * cw + i * gap + gap / 2 for i in range(4)]
below_ext = ext_y - 14  # just under the external-systems row, still clear

# 1) FastAPI routes -> store: drop through the Gmail/Calendar gap, clear
#    of the graph container's node row too (which has a wide gap between
#    propose_node and approval_node at this x).
poly_arrow(
    c, [(260, api_y), (gap_x[0], api_y - 10), (gap_x[0], below_ext), (store_top_cx - 220, store_y + store_h)],
    color=GREEN, dashed=True, label="audit log", label_seg=2,
)

# 2) Action graph (approval_node) -> store: jog sideways within the
#    graph->connector gap band before dropping through the Excel/
#    Salesforce gap.
poly_arrow(
    c, [(approval_cx, node_y), (approval_cx, graph_y + 7), (gap_x[2], graph_y + 7),
        (gap_x[2], below_ext), (store_top_cx, store_y + store_h)],
    color=GREEN, dashed=True, label="audit log", label_seg=3,
)

# 3) Connector layer -> store: drop straight through the Salesforce/Jira
#    gap, already clear of both rows below it.
poly_arrow(
    c, [(gap_x[3], conn_y), (gap_x[3], below_ext), (store_top_cx + 220, store_y + store_h)],
    color=GREEN, dashed=True, label="audit log", label_seg=1,
)

# ---- Legend ------------------------------------------------------------------
leg_x, leg_y, leg_w, leg_h = graph_x + graph_w + 20, store_y, human_w, store_h + 22
c.saveState()
c.setStrokeColor(INK)
c.setLineWidth(1.1)
c.roundRect(leg_x, leg_y, leg_w, leg_h, 6, fill=0, stroke=1)
c.setFont("Helvetica-Bold", 8.5)
c.setFillColor(INK)
c.drawString(leg_x + 10, leg_y + leg_h - 16, "Legend")
items = [
    (INK, False, "call / data flow"),
    (GREEN, True, "audit log write (every call)"),
    (RED, False, "gated write — needs human approval"),
]
ly = leg_y + leg_h - 34
for color, dashed, text in items:
    arrow(c, leg_x + 10, ly, leg_x + 34, ly, color=color, dashed=dashed, width=1.3)
    c.setFont("Helvetica", 7.4)
    c.setFillColor(INK)
    c.drawString(leg_x + 40, ly - 3, text)
    ly -= 15
c.restoreState()

# ---- Footer note -------------------------------------------------------------
c.setFont("Helvetica-Oblique", 8)
c.setFillColor(GRAY)
c.drawString(40, 18,
             "Core guardrail: a write/action method is only ever called with dry_run=False from execute_node, after approval_node's interrupt() returns an approved decision. See docs/security-guardrails.md.")

c.showPage()
c.save()
print("wrote", OUT)
