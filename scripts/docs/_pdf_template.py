# -*- coding: utf-8 -*-
"""Shared ReportLab/Platypus building blocks for this repo's per-layer
reference PDFs (see scripts/docs/README.md and CLAUDE.md's "Reference
documents" section). Extracted from gen_mcp_server_pdf.py so every
future per-layer doc imports one copy of these helpers instead of
re-pasting them.

Not a dependency of the application itself -- only used by the
scripts in this directory. Requires `pip install reportlab` (not part
of this repo's own pyproject.toml extras).
"""

from __future__ import annotations

import textwrap

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import HRFlowable, Paragraph, Preformatted, Table, TableStyle

# -- Palette, shared across every reference doc ------------------------------

INK = colors.HexColor("#1a1a2e")
BLUE = colors.HexColor("#2563eb")
GRAY = colors.HexColor("#6b7280")
GRAY_FILL = colors.HexColor("#f3f4f6")
CODE_FILL = colors.HexColor("#f6f8fa")
CODE_BORDER = colors.HexColor("#d0d7de")
AMBER = colors.HexColor("#b45309")
GREEN = colors.HexColor("#15803d")
RED = colors.HexColor("#b91c1c")

PAGE_W, PAGE_H = letter
MARGIN = 0.85 * inch
USABLE_W = PAGE_W - 2 * MARGIN

styles = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=21, leading=25, textColor=INK),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10.5, leading=14, textColor=GRAY, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=BLUE, spaceBefore=16, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=8, spaceAfter=3),
    "bodyleft": ParagraphStyle("bodyleft", fontName="Helvetica", fontSize=9.6, leading=14, textColor=INK, alignment=TA_LEFT, spaceAfter=6),
    "quote": ParagraphStyle("quote", fontName="Helvetica-Oblique", fontSize=9.4, leading=13.5, textColor=INK, leftIndent=14, spaceAfter=6),
    "codecaption": ParagraphStyle("codecaption", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=GRAY, spaceBefore=4, spaceAfter=2),
    "tablehdr": ParagraphStyle("tablehdr", fontName="Helvetica-Bold", fontSize=8.6, leading=11, textColor=INK),
    "tablecell": ParagraphStyle("tablecell", fontName="Helvetica", fontSize=8.4, leading=11.5, textColor=INK),
}


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap_code(text: str, width: int = 96) -> str:
    """Soft-wrap a code block's long lines without breaking words/hyphens,
    preserving each line's original indentation."""
    out_lines = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        avail = width - indent
        if len(stripped) <= avail or avail <= 10:
            out_lines.append(line)
            continue
        pieces = textwrap.wrap(
            stripped, width=avail, break_long_words=False, break_on_hyphens=False,
            subsequent_indent="    ",
        )
        for p in pieces:
            out_lines.append(" " * indent + p)
    return "\n".join(out_lines)


def code_block(text: str, width_frac: float = 1.0):
    """A shaded, bordered monospace code box -- the standard way every
    reference doc shows a real snippet from the repo."""
    style = ParagraphStyle("code", fontName="Courier", fontSize=7.7, leading=10.2, textColor=INK)
    pre = Preformatted(wrap_code(text), style)
    tbl = Table([[pre]], colWidths=[USABLE_W * width_frac])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_FILL),
        ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def quote_block(text: str):
    """A left-rule blockquote -- used to quote a docstring/comment from
    the actual source verbatim, distinct from the surrounding prose."""
    p = Paragraph(text, styles["quote"])
    tbl = Table([[p]], colWidths=[USABLE_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRAY_FILL),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def h1(text):
    return Paragraph(esc(text), styles["h1"])


def h2(text):
    return Paragraph(esc(text), styles["h2"])


def bl(text):
    """Body paragraph. `text` may contain simple inline markup (<b>,
    <i>) -- it is NOT escaped, so callers pass pre-escaped/markup-safe
    text (use esc() first on any raw, untrusted, or code-derived string)."""
    return Paragraph(text, styles["bodyleft"])


def caption(text):
    return Paragraph(esc(text), styles["codecaption"])


def rule():
    return HRFlowable(width="100%", thickness=0.6, color=CODE_BORDER, spaceBefore=2, spaceAfter=10)


def simple_table(rows, col_widths, header=True):
    """rows: list of lists of pre-built markup strings (first row is the
    header if header=True). Zebra-free, bordered, top-aligned -- the
    standard reference-table look used throughout these docs."""
    style_rows = []
    for i, row in enumerate(rows):
        st = styles["tablehdr"] if (header and i == 0) else styles["tablecell"]
        style_rows.append([Paragraph(c, st) for c in row])
    t = Table(style_rows, colWidths=col_widths)
    ts = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, CODE_BORDER),
        ("BOX", (0, 0), (-1, -1), 0.8, CODE_BORDER),
    ]
    if header:
        ts.append(("BACKGROUND", (0, 0), (-1, 0), GRAY_FILL))
    t.setStyle(TableStyle(ts))
    return t


def footer(doc_title: str):
    """Standard page-footer callback: "<doc_title>" on the left, "Page N"
    on the right, above a thin rule. Pass to SimpleDocTemplate.build()
    as both onFirstPage and onLaterPages."""

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(MARGIN, 0.5 * inch, doc_title)
        canvas.drawRightString(PAGE_W - MARGIN, 0.5 * inch, f"Page {doc.page}")
        canvas.setStrokeColor(CODE_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.62 * inch, PAGE_W - MARGIN, 0.62 * inch)
        canvas.restoreState()

    return on_page
