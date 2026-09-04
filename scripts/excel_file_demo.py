"""Manual smoke-test for the local/Google Drive Excel connector
(src/apm/tools/excel_file_tool.py) — not part of the automated test
suite (that uses a fake source, see tests/test_excel_file_tool.py).

Only the file itself is required; sheet_name and range_address are
optional and default to the workbook's first worksheet and its whole
used range (see ExcelFileTool.read_range) — pass them to read something
more specific.

Local file usage (no credentials needed):
  python scripts/excel_file_demo.py local <path.xlsx> [sheet_name] [range_address]
  python scripts/excel_file_demo.py local ./workbook.xlsx
  python scripts/excel_file_demo.py local ./workbook.xlsx Sheet1 A1:D10

Google Drive usage:
  Setup (one-time): copy .env.example to .env, fill in GOOGLE_CLIENT_ID /
  GOOGLE_CLIENT_SECRET (Google Cloud Console -> enable the Drive API on
  the same OAuth client used for Gmail/Calendar).

  # <file> can be either a Drive file id, or the file's name (e.g.
  # "APM_Invoice_Details.xlsx") -- a name is resolved to an id via a
  # Drive search first. First run opens a browser consent screen and
  # caches a token locally (.google_drive_token.json, gitignored). If
  # zero or more than one file shares that name, this exits with an
  # error instead of guessing -- use --list or the file id to be
  # unambiguous.
  python scripts/excel_file_demo.py gdrive --list
  python scripts/excel_file_demo.py gdrive <file_id_or_name> [sheet_name] [range_address]

Both modes only call read-only methods here — nothing is written to the
workbook.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.excel_file_tool import (
    DEFAULT_DRIVE_TOKEN_PATH,
    GOOGLE_DRIVE_SCOPE,
    build_gdrive_excel_tool,
    build_local_excel_tool,
    resolve_drive_file_id as _resolve_drive_file_id,
)


def _drive_service():
    from apm_connectors.tools.google_auth import load_credentials
    from googleapiclient.discovery import build

    settings = load_settings()
    credentials = load_credentials(settings, scopes=[GOOGLE_DRIVE_SCOPE], token_path=DEFAULT_DRIVE_TOKEN_PATH)
    return build("drive", "v3", credentials=credentials)


def list_drive_files() -> None:
    from apm_connectors.tools.excel_file_tool import EXCEL_MIME_TYPE

    response = _drive_service().files().list(q=f"mimeType='{EXCEL_MIME_TYPE}'", fields="files(id, name)").execute()
    for item in response.get("files", []):
        print(f"{item['id']}  {item['name']}")


def resolve_drive_file_id(file_id_or_name: str) -> str:
    """Thin CLI wrapper over apm_connectors.tools.excel_file_tool.resolve_drive_file_id
    (shared with build_configured_excel_tool, so the API/UI resolves a
    configured name the same way this script does) -- converts its
    ValueError (no match, or more than one) into a clean SystemExit
    message instead of a raw traceback.
    """
    try:
        return _resolve_drive_file_id(load_settings(), file_id_or_name)
    except ValueError as exc:
        raise SystemExit(
            f"{exc} Run `python scripts/excel_file_demo.py gdrive --list` to see what's available."
        ) from None


def build_tool(mode: str, file_id_or_name: str):
    """Resolve `mode` ("local" or "gdrive") + a path/id/name to a built
    ExcelFileTool. Shared with scripts/excel_file_write_demo.py so the
    local-vs-Drive resolution logic (including Drive name lookup) lives
    in exactly one place.
    """
    store = StateStore()
    if mode == "local":
        return build_local_excel_tool(store, file_id_or_name)
    if mode == "gdrive":
        file_id = resolve_drive_file_id(file_id_or_name)
        settings = load_settings()
        return build_gdrive_excel_tool(store, settings, file_id=file_id)
    raise ValueError(f"unknown mode: {mode!r} (expected 'local' or 'gdrive')")


def run(tool, sheet_name: str | None, address: str | None) -> None:
    # Not tool.health_check() -- it deliberately swallows the real
    # exception (see BaseTool.health_check's docstring: "must never
    # raise"), which is right for a UI connectivity indicator but
    # useless for diagnosing a failure at the terminal. Call the real
    # method and let the actual error (e.g. googleapiclient's HttpError,
    # with its status code and message) print instead.
    try:
        worksheets = tool.list_worksheets(process_id="demo")
    except Exception as exc:
        print(f"Failed to read the workbook: {type(exc).__name__}: {exc}")
        return

    print(f"Worksheets: {worksheets}\n")

    data = tool.read_range(process_id="demo", sheet_name=sheet_name, address=address)
    print(f"{data.sheet_name}!{data.address}")
    for row in data.values:
        print(row)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    mode, *rest = args

    if mode == "local":
        if not rest or len(rest) > 3:
            print(__doc__)
            return
        path, *optional = rest
        sheet_name = optional[0] if len(optional) > 0 else None
        address = optional[1] if len(optional) > 1 else None
        run(build_tool("local", path), sheet_name, address)
        return

    if mode == "gdrive":
        if rest and rest[0] == "--list":
            list_drive_files()
            return
        if not rest or len(rest) > 3:
            print(__doc__)
            return
        file_id_or_name, *optional = rest
        sheet_name = optional[0] if len(optional) > 0 else None
        address = optional[1] if len(optional) > 1 else None
        run(build_tool("gdrive", file_id_or_name), sheet_name, address)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
