# Reference-doc generators

Tooling for the per-layer PDF reference docs described in `CLAUDE.md`'s
"Reference documents" section — kept here so regenerating or extending
one doesn't mean rebuilding the ReportLab plumbing from scratch.

Not a dependency of the application itself. Requires:

```bash
pip install reportlab      # every script here
pip install pymupdf        # only for the QA-rendering step, and for
                            # gen_architecture_pdf.py's page merge
```

## What's here

- **`_pdf_template.py`** — shared Platypus building blocks for a
  text-only deep dive: the color palette, paragraph styles, and
  helpers (`h1`, `bl`, `code_block`, `quote_block`, `simple_table`,
  `caption`, `rule`, `footer`). Used by `gen_mcp_server_pdf.py` and by
  `gen_architecture_deepdive.py`'s pages 3+.
- **`_canvas_template.py`** — shared raw-canvas
  (`reportlab.pdfgen.canvas`) building blocks for a hand-positioned
  landscape-A3 diagram/reference page: `box`, `container`, `arrow`,
  `poly_arrow`, `table`, `wrap_text`, plus the same color palette.
  Used by `gen_architecture_diagram.py` and
  `gen_architecture_reference.py`.
- **`gen_mcp_server_pdf.py`** → `docs/mcp-server-reference.pdf` — the
  text-only-deep-dive shape (13 sections: MCP basics for a newcomer,
  a pattern-by-pattern deep dive into `src/apm_connectors_mcp/`, a
  9-step cross-layer walkthrough, the full 18-tool inventory, a
  vocabulary cheat-sheet). The example to copy for a new single-layer
  reference doc.
- **`gen_architecture_diagram.py`**, **`gen_architecture_reference.py`**,
  **`gen_architecture_deepdive.py`**, **`gen_architecture_pdf.py`** →
  `docs/architecture.pdf` — the diagram-+-reference-+-deep-dive shape.
  The first three each produce one part; `gen_architecture_pdf.py`
  runs all three and merges them. Run the orchestrator, not the parts,
  unless you're debugging one page in isolation.

## The two document shapes in use

1. **Text-only deep dive** (`gen_mcp_server_pdf.py`) — a single
   Platypus flow: title, then numbered `h1` sections mixing prose
   (`bl`), real code snippets quoted from the source (`code_block`),
   quoted docstrings/comments (`quote_block`), and reference tables
   (`simple_table`), closing with a vocabulary cheat-sheet. Portrait
   Letter, one running footer via `footer(title)`.
2. **Diagram + reference + deep dive** (`gen_architecture_*.py`, →
   `docs/architecture.pdf`) — page 1 is a hand-drawn landscape-A3
   flowchart (`_canvas_template.py`'s `box`/`arrow`/`poly_arrow`/
   `container`), page 2 is reference tables on the same canvas
   (`_canvas_template.py`'s `table`), then pages 3+ are the same
   Platypus deep-dive format as shape 1, built via
   `_pdf_template.py`. `gen_architecture_pdf.py` runs the three
   sub-scripts (writing intermediate per-page PDFs to `_build/`,
   gitignored) and merges them with `pymupdf`'s `insert_pdf`. Use
   this shape for a doc that needs an at-a-glance system diagram up
   front — e.g. the whole-system architecture doc, or a
   deployment/infra doc.

## Writing a new one

1. **Read the current source first.** Every fact in these docs is
   pulled from the actual code at generation time, not memory — grep
   the relevant module(s), read them in full, and quote real
   snippets rather than paraphrasing from an earlier doc.
2. Pick a shape (above) and copy the matching example(s). For a
   diagram page, lean on `_canvas_template.py`'s `poly_arrow` to route
   a connector *around* another box rather than letting a straight
   `arrow` cross through it — nearly every layout bug caught in this
   doc set was a line or a label overlapping a box it shouldn't.
3. Close a deep-dive portion with a vocabulary cheat-sheet table if it
   introduces more than a few new terms.
4. Run it, then **render every page to PNG and look at it** before
   treating it as done:

   ```python
   import fitz
   doc = fitz.open("docs/<name>.pdf")
   for i, page in enumerate(doc):
       page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(f"/tmp/qa_p{i+1}.png")
   ```

   This has caught a real layout bug (clipped text, an overflowing
   box) in nearly every doc built this way — it's not optional.
5. Commit the script(s) *and* the generated PDF together, so `docs/`
   never has one without the other.

## Regenerating an existing one

```bash
python scripts/docs/gen_mcp_server_pdf.py        # -> docs/mcp-server-reference.pdf
python scripts/docs/gen_architecture_pdf.py      # -> docs/architecture.pdf (runs all 3 sub-scripts + merges)
```

Each writes to its `docs/*.pdf` path by default; every script accepts
an env-var override to preview without touching the committed file
(`OUT_OVERRIDE` for `gen_mcp_server_pdf.py`; `DIAGRAM_OUT`/
`REFERENCE_OUT`/`DEEPDIVE_OUT`/`ARCHITECTURE_OUT` for the architecture
scripts). Re-run after any change to the layer(s) a doc documents —
each script's module docstring notes what it should be kept in sync
with.
