"""Manual smoke-test for ExcelFileTool.write_range
(src/apm/tools/excel_file_tool.py) against a real local or Google Drive
workbook -- the write counterpart to scripts/excel_file_demo.py, which
is deliberately read-only.

Like every write/action method in this project, write_range defaults to
dry_run=True and is never called with dry_run=False without an explicit
human approval step (see .claude/skills/tool-integration/SKILL.md's
non-negotiable rule): this script reads the current value, shows the
proposed change (a dry run), asks "Approve this write? [y/N]" at the
terminal, and only writes for real if you type y. Nothing is silently
written.

Usage:
  python scripts/excel_file_write_demo.py local <path.xlsx> <sheet_name> <address> <value> [<value>...]
  python scripts/excel_file_write_demo.py gdrive <file_id_or_name> <sheet_name> <address> <value> [<value>...]

Writes a single row -- <address> is one cell or a one-row range (e.g.
"C2" or "C2:D2"); pass one <value> per cell in that row, in order. For a
multi-row write, call ExcelFileTool.write_range directly (see
tests/test_excel_file_tool.py for the shape) -- this script is a smoke
test, not a general-purpose editor.

Examples:
  python scripts/excel_file_write_demo.py local ./workbook.xlsx Renewals C2 Contacted
  python scripts/excel_file_write_demo.py gdrive APM_Invoice_Details.xlsx Sheet1 D5 Paid 2026-09-03
"""

from __future__ import annotations

import sys

from excel_file_demo import build_tool  # sibling script -- shares the local/gdrive resolution logic


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 5 or args[0] not in ("local", "gdrive"):
        print(__doc__)
        return

    mode, file_id_or_name, sheet_name, address, *values = args

    try:
        tool = build_tool(mode, file_id_or_name)
    except Exception as exc:
        print(f"Failed to open the workbook: {type(exc).__name__}: {exc}")
        return

    try:
        before = tool.read_range(process_id="write-demo", sheet_name=sheet_name, address=address)
    except Exception as exc:
        print(f"Failed to read the workbook: {type(exc).__name__}: {exc}")
        return

    print(f"Current value at {before.sheet_name}!{before.address}: {before.values}\n")

    row_values = [values]
    proposal = tool.write_range(process_id="write-demo", sheet_name=sheet_name, address=address, values=row_values)
    print(f"Proposed: {proposal.description}")
    print(f"Payload: {proposal.details}\n")

    answer = input("Approve this write? [y/N] ").strip().lower()
    if answer != "y":
        print("Not approved -- nothing written.")
        return

    result = tool.write_range(
        process_id="write-demo", sheet_name=sheet_name, address=address, values=row_values, dry_run=False
    )
    print(f"\nResult: {result.description}")
    print(f"Details: {result.details}")

    after = tool.read_range(process_id="write-demo", sheet_name=sheet_name, address=address)
    print(f"\nRe-read {after.sheet_name}!{after.address}: {after.values}")


if __name__ == "__main__":
    main()
