"""Manual smoke-test for the Gmail connector — run this yourself once you
have real Google OAuth credentials; it is not part of the automated test
suite (those use a fake client, see tests/test_gmail_tool.py).

Setup (one-time):
  1. Follow .env.example / docs/capability-map.md to create a Google Cloud
     OAuth client and enable the Gmail API, using your sandbox account.
  2. Copy .env.example to .env and fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET.
  3. pip install -e .

Usage:
  python scripts/gmail_demo.py "newer_than:30d"

The first run opens a browser for the OAuth consent screen and caches a
token locally (.google_token.json, gitignored). This only calls read-only
methods — nothing is sent or changed in the mailbox.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.gmail_tool import build_gmail_tool


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    settings = load_settings()
    store = StateStore()
    tool = build_gmail_tool(store, settings)

    if not tool.health_check():
        print("Gmail connector health check failed — check your .env and OAuth setup.")
        return

    print(f"Searching Gmail for: {query!r}\n")
    for email in tool.search_emails(process_id="demo", query=query, max_results=5):
        print(f"- [{email.received_at}] {email.sender}: {email.subject}")
        print(f"    {email.snippet}\n")


if __name__ == "__main__":
    main()
