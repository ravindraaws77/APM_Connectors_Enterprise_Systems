"""Manual smoke-test for the Excel connector — run this yourself once you
have a real Azure AD app registration; it is not part of the automated
test suite (those use a fake client, see tests/test_excel_tool.py).

Setup (one-time):
  1. Azure Portal -> Azure Active Directory -> App registrations -> New
     registration. Supported account type: your choice; no redirect URI
     needed (device-code flow). API permissions -> Microsoft Graph ->
     Delegated -> Files.Read -> grant admin consent if required.
  2. Copy .env.example to .env, fill in MS_GRAPH_CLIENT_ID / MS_GRAPH_TENANT_ID
     (MS_GRAPH_CLIENT_SECRET is not needed for this device-code flow).
  3. pip install -e .
  4. Put a workbook (.xlsx) in the OneDrive of the account you'll sign in
     with, with at least one worksheet and some data.

Usage:
  # First, find your workbook's drive item id:
  python scripts/excel_demo.py --list

  # Then read a range from it:
  python scripts/excel_demo.py <item_id> <sheet_name> <range_address>
  python scripts/excel_demo.py 01ABCDEFGHIJK Sheet1 A1:D10

The first run prints a URL + code for the device-code sign-in flow and
caches a token locally (.ms_graph_token_cache.json, gitignored). This only
calls read-only methods — nothing is written to the workbook.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.excel_tool import EXCEL_READONLY_SCOPE, build_excel_tool
from apm_connectors.tools.ms_graph_auth import acquire_access_token


def list_files() -> None:
    import requests

    settings = load_settings()
    token = acquire_access_token(settings, scopes=[EXCEL_READONLY_SCOPE])
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/drive/root/children",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    for item in response.json().get("value", []):
        if item.get("name", "").lower().endswith((".xlsx", ".xlsm")):
            print(f"{item['id']}  {item['name']}")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        list_files()
        return

    if len(args) != 3:
        print(__doc__)
        return

    item_id, sheet_name, address = args
    settings = load_settings()
    store = StateStore()
    tool = build_excel_tool(store, settings, item_id=item_id)

    if not tool.health_check():
        print("Excel connector health check failed — check your .env, Azure app, and item id.")
        return

    print(f"Worksheets: {tool.list_worksheets(process_id='demo')}\n")

    data = tool.read_range(process_id="demo", sheet_name=sheet_name, address=address)
    print(f"{data.sheet_name}!{data.address}")
    for row in data.values:
        print(row)


if __name__ == "__main__":
    main()
