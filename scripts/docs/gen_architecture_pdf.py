"""Build docs/architecture.pdf end to end: runs the diagram, reference,
and deep-dive scripts in this directory, then merges their output into
one PDF. See scripts/docs/README.md for the doc shape and how to
extend it.

    python scripts/docs/gen_architecture_pdf.py

Requires `pip install reportlab pymupdf`. Writes docs/architecture.pdf
by default (override with the ARCHITECTURE_OUT env var). Intermediate
per-page PDFs land in scripts/docs/_build/ (gitignored) -- inspect
those individually if you need to debug one page without re-merging.
"""

import os
import subprocess
import sys
from pathlib import Path

import fitz  # pymupdf

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
BUILD_DIR = HERE / "_build"
OUT = Path(os.environ.get("ARCHITECTURE_OUT", REPO_ROOT / "docs" / "architecture.pdf"))

STEPS = [
    ("gen_architecture_diagram.py", BUILD_DIR / "architecture-diagram.pdf"),
    ("gen_architecture_reference.py", BUILD_DIR / "architecture-reference.pdf"),
    ("gen_architecture_deepdive.py", BUILD_DIR / "architecture-deepdive.pdf"),
]


def main() -> None:
    for script, _ in STEPS:
        subprocess.run([sys.executable, str(HERE / script)], check=True, cwd=HERE)

    out = fitz.open()
    for _, page_pdf in STEPS:
        out.insert_pdf(fitz.open(page_pdf))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(str(OUT))
    print(f"wrote {OUT} ({out.page_count} pages)")


if __name__ == "__main__":
    main()
