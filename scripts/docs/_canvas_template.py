"""Shared raw-canvas (reportlab.pdfgen.canvas) building blocks for this
repo's diagram + reference pages -- the landscape-A3 pages of the
"diagram + reference + deep dive" doc shape described in
scripts/docs/README.md (currently docs/architecture.pdf's pages 1-2).

Distinct from _pdf_template.py: that one is for Platypus-flowed text
(the deep-dive pages, portrait Letter); this one is for hand-positioned
boxes/arrows/tables on a single landscape-A3 canvas, where every
coordinate is placed explicitly rather than flowed.

Not a dependency of the application itself. Requires
`pip install reportlab`.
"""

from __future__ import annotations

import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth

# -- Palette, shared with _pdf_template.py's INK/BLUE/GRAY/GREEN hues so a
#    diagram page and its deep-dive pages read as one document. -----------

INK = colors.HexColor("#1a1a2e")
BLUE = colors.HexColor("#2563eb")
BLUE_FILL = colors.HexColor("#eff6ff")
PURPLE = colors.HexColor("#6d28d9")
PURPLE_FILL = colors.HexColor("#f5f3ff")
GREEN = colors.HexColor("#15803d")
GREEN_FILL = colors.HexColor("#f0fdf4")
AMBER = colors.HexColor("#b45309")
AMBER_FILL = colors.HexColor("#fffbeb")
GRAY = colors.HexColor("#6b7280")
GRAY_FILL = colors.HexColor("#f3f4f6")
RED = colors.HexColor("#b91c1c")
RED_FILL = colors.HexColor("#fef2f2")
WHITE = colors.white

PAGE_W, PAGE_H = landscape(A3)


def wrap_text(c, text, font, size, max_width):
    """Word-wrap `text` to `max_width` at `font`/`size`, measuring with
    the canvas's own stringWidth so it matches what actually renders."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def box(c, x, y, w, h, lines, *, fill=WHITE, stroke=INK, text_color=INK,
        title_size=9.5, body_size=7.6, line_width=1.1, radius=6, align="center",
        title_font="Helvetica-Bold", body_font="Helvetica", pad=6):
    """A rounded-rect node: `lines[0]` renders as a bold title, the rest
    as wrapped body text, vertically centered as a block."""
    c.saveState()
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)

    all_wrapped = []
    for i, raw in enumerate(lines):
        font = title_font if i == 0 else body_font
        size = title_size if i == 0 else body_size
        for wl in wrap_text(c, raw, font, size, w - 2 * pad):
            all_wrapped.append((wl, font, size))

    total_h = sum(s * 1.25 for _, _, s in all_wrapped)
    cy = y + h / 2 + total_h / 2 - all_wrapped[0][2] * 0.9 if all_wrapped else y + h / 2

    ty = cy
    for text, font, size in all_wrapped:
        c.setFont(font, size)
        c.setFillColor(text_color)
        if align == "center":
            c.drawCentredString(x + w / 2, ty, text)
        else:
            c.drawString(x + pad, ty, text)
        ty -= size * 1.25
    c.restoreState()


def container(c, x, y, w, h, title, *, stroke=GRAY, fill=None, title_color=GRAY):
    """A large dashed-border region grouping several boxes, labeled top-left."""
    c.saveState()
    c.setStrokeColor(stroke)
    c.setLineWidth(1.3)
    c.setDash(3, 2)
    if fill:
        c.setFillColor(fill)
        c.roundRect(x, y, w, h, 8, fill=1, stroke=1)
    else:
        c.roundRect(x, y, w, h, 8, fill=0, stroke=1)
    c.setDash()
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(title_color)
    c.drawString(x + 10, y + h - 13, title)
    c.restoreState()


def arrow(c, x1, y1, x2, y2, *, color=INK, dashed=False, width=1.2, label=None,
          label_bg=WHITE, label_size=7, double=False, curve=None):
    """A straight arrow from (x1,y1) to (x2,y2), optionally dashed/labeled."""
    c.saveState()
    c.setStrokeColor(color)
    c.setLineWidth(width)
    if dashed:
        c.setDash(4, 3)
    else:
        c.setDash()
    c.line(x1, y1, x2, y2)

    def head(px, py, angle):
        size = 6.5
        a1 = angle + math.radians(150)
        a2 = angle - math.radians(150)
        p1 = (px + size * math.cos(a1), py + size * math.sin(a1))
        p2 = (px + size * math.cos(a2), py + size * math.sin(a2))
        c.setDash()
        c.setFillColor(color)
        p = c.beginPath()
        p.moveTo(px, py)
        p.lineTo(*p1)
        p.lineTo(*p2)
        p.close()
        c.drawPath(p, fill=1, stroke=0)

    ang = math.atan2(y2 - y1, x2 - x1)
    head(x2, y2, ang)
    if double:
        head(x1, y1, ang + math.pi)

    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        c.setFont("Helvetica", label_size)
        tw = stringWidth(label, "Helvetica", label_size)
        c.setFillColor(label_bg)
        c.rect(mx - tw / 2 - 3, my - 5, tw + 6, 11, fill=1, stroke=0)
        c.setFillColor(color)
        c.drawCentredString(mx, my - 1.5, label)
    c.restoreState()


def poly_arrow(c, points, *, color=INK, dashed=False, width=1.2, label=None,
               label_bg=WHITE, label_size=7, label_seg=-1):
    """Draw connected straight segments through `points`; arrowhead only at
    the final point, in the direction of the last segment. `label_seg`
    picks which segment (0-indexed) carries the label (default: longest
    segment, picked automatically if -1). Use this instead of arrow()
    whenever a straight line would cross another box -- route it around
    via an intermediate waypoint instead of letting it overlap.
    """
    c.saveState()
    c.setStrokeColor(color)
    c.setLineWidth(width)
    if dashed:
        c.setDash(4, 3)
    else:
        c.setDash()
    for i in range(len(points) - 1):
        c.line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
    c.setDash()

    (x1, y1), (x2, y2) = points[-2], points[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 6.5
    a1, a2 = ang + math.radians(150), ang - math.radians(150)
    p1 = (x2 + size * math.cos(a1), y2 + size * math.sin(a1))
    p2 = (x2 + size * math.cos(a2), y2 + size * math.sin(a2))
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x2, y2)
    p.lineTo(*p1)
    p.lineTo(*p2)
    p.close()
    c.drawPath(p, fill=1, stroke=0)

    if label:
        seg = label_seg
        if seg < 0:
            lengths = [math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
                       for i in range(len(points) - 1)]
            seg = lengths.index(max(lengths))
        (sx1, sy1), (sx2, sy2) = points[seg], points[seg + 1]
        mx, my = (sx1 + sx2) / 2, (sy1 + sy2) / 2
        c.setFont("Helvetica", label_size)
        tw = stringWidth(label, "Helvetica", label_size)
        c.setFillColor(label_bg)
        c.rect(mx - tw / 2 - 3, my - 5, tw + 6, 11, fill=1, stroke=0)
        c.setFillColor(color)
        c.drawCentredString(mx, my - 1.5, label)
    c.restoreState()


def table(c, x, y, w, col_widths, headers, rows, *, row_h=16, header_h=18,
          font_size=7.8, header_size=8.4, zebra=True):
    """A plain bordered/zebra-striped reference table, top-left corner
    at (x, y). Cells wrap up to 3 lines (extra lines are silently
    dropped -- widen the column or raise row_h if you see this clip).
    Returns the y-coordinate of the table's bottom edge, so callers can
    chain `next_y = table(...)` for whatever comes next on the page.
    """
    total_h = header_h + row_h * len(rows)
    c.saveState()
    c.setStrokeColor(GRAY)
    c.setLineWidth(0.8)
    c.setFillColor(colors.HexColor("#e5e7eb"))
    c.rect(x, y - header_h, w, header_h, fill=1, stroke=1)
    c.setFont("Helvetica-Bold", header_size)
    c.setFillColor(INK)
    cx = x
    for cw, h in zip(col_widths, headers):
        c.drawString(cx + 6, y - header_h + 6, h)
        cx += cw
    ry = y - header_h
    for i, row in enumerate(rows):
        if zebra and i % 2 == 1:
            c.setFillColor(colors.HexColor("#f9fafb"))
            c.rect(x, ry - row_h, w, row_h, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#e5e7eb"))
        c.rect(x, ry - row_h, w, row_h, fill=0, stroke=1)
        cx = x
        c.setFont("Helvetica", font_size)
        c.setFillColor(INK)
        for cw, val in zip(col_widths, row):
            cell_lines = wrap_text(c, str(val), "Helvetica", font_size, cw - 10)
            cy = ry - 11
            for cl in cell_lines[:3]:
                c.drawString(cx + 6, cy, cl)
                cy -= 9.5
            cx += cw
        ry -= row_h
    c.setStrokeColor(GRAY)
    c.setLineWidth(1.1)
    c.rect(x, y - total_h, w, total_h, fill=0, stroke=1)
    c.restoreState()
    return y - total_h
