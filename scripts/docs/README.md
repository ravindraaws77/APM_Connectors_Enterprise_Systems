# Reference-doc generators

Tooling for the per-layer PDF reference docs described in `CLAUDE.md`'s
"Reference documents" section — kept here so regenerating or extending
one doesn't mean rebuilding the ReportLab plumbing from scratch.

Not a dependency of the application itself. Requires:

```bash
pip install reportlab      # every script here
pip install pymupdf        # only for the QA/merge step below
```

## What's here

- **`_pdf_template.py`** — the shared Platypus building blocks every
  script in this directory imports: the color palette, paragraph
  styles, and helpers (`h1`, `bl`, `code_block`, `quote_block`,
  `simple_table`, `caption`, `rule`, `footer`). Extracted from the
  first script (`gen_mcp_server_pdf.py`) once a second one would have
  needed to duplicate it — read this file before writing a new one.
- **`gen_mcp_server_pdf.py`** — generates `docs/mcp-server-reference.pdf`
  (13 sections: MCP basics for a newcomer, then a pattern-by-pattern
  deep dive into `src/apm_connectors_mcp/`, a 9-step cross-layer
  walkthrough, the full 18-tool inventory, a vocabulary cheat-sheet).
  The concrete example to copy when starting a new one.

## The two document shapes in use

Two distinct formats have been used in this repo, both described in
`CLAUDE.md`:

1. **Text-only deep dive** (what's committed here) — a single
   Platypus flow: title, then numbered `h1` sections mixing prose
   (`bl`), real code snippets quoted from the source (`code_block`),
   quoted docstrings/comments (`quote_block`), and reference tables
   (`simple_table`), closing with a vocabulary cheat-sheet. Portrait
   Letter, one running footer via `footer(title)`. This is what
   `gen_mcp_server_pdf.py` produces, and the pattern to follow for a
   new single-layer reference doc.
2. **Diagram + reference + deep dive** (used for `docs/architecture.pdf`,
   generator not currently committed) — page 1 is a hand-drawn
   landscape-A3 flowchart (raw `reportlab.pdfgen.canvas`, not
   Platypus: custom `box`/`arrow`/`poly_arrow`/`container` helpers),
   page 2 is reference tables on the same canvas, then pages 3+ are
   the same Platypus deep-dive format as above, merged together with
   `pymupdf`'s `insert_pdf`. Use this shape for a doc that needs an
   at-a-glance system diagram up front — e.g. the whole-system
   architecture doc, or a deployment/infra doc. The canvas-drawing
   helpers aren't in `_pdf_template.py` yet; if you build one of
   these, consider extracting them the same way once there's a second
   user.

## Writing a new one

1. **Read the current source first.** Every fact in these docs is
   pulled from the actual code at generation time, not memory — grep
   the relevant module(s), read them in full, and quote real
   snippets rather than paraphrasing from an earlier doc.
2. Copy `gen_mcp_server_pdf.py`'s structure: title/subtitle, `rule()`,
   then `h1` sections. Keep sections self-contained and concrete —
   real code, then one or two paragraphs explaining *why* it's built
   that way, not just what it does.
3. Close with a vocabulary cheat-sheet table if the doc introduces
   more than a few new terms.
4. Run it (`python scripts/docs/gen_<name>_pdf.py`), then **render
   every page to PNG and look at it** before treating it as done:

   ```python
   import fitz
   doc = fitz.open("docs/<name>.pdf")
   for i, page in enumerate(doc):
       page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(f"/tmp/qa_p{i+1}.png")
   ```

   This has caught a real layout bug (clipped text, an overflowing
   box) in nearly every doc built this way — it's not optional.
5. Commit the script *and* the generated PDF together, so `docs/`
   never has one without the other.

## Regenerating an existing one

```bash
python scripts/docs/gen_mcp_server_pdf.py
```

Writes to `docs/mcp-server-reference.pdf` by default (override with
the `OUT_OVERRIDE` env var, e.g. to preview without touching the
committed file). Re-run after any change to the layer it documents —
`gen_mcp_server_pdf.py`'s docstring notes exactly which source files
it should be kept in sync with.
