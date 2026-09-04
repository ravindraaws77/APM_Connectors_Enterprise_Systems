"""Manual smoke-test for the Calendar connector — run this yourself once
you have real Google OAuth credentials; it is not part of the automated
test suite (those use a fake client, see tests/test_calendar_tool.py).

Setup: same Google Cloud project as scripts/gmail_demo.py — just also
enable the Google Calendar API there.

Usage:
  python scripts/calendar_demo.py "renewal"

The first run opens a browser for the OAuth consent screen and caches a
token locally (.google_token.json, gitignored). This only calls read-only
methods — nothing is created or changed in the calendar.

Note: if you already ran gmail_demo.py, this will re-prompt for consent
because the two scripts currently request separate scopes against the
same token cache (see the note in apm/tools/google_auth.py) — that's a
known follow-up for phase 5, when both tools are wired into the agent
together.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import build_calendar_tool


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else None
    settings = load_settings()
    store = StateStore()
    tool = build_calendar_tool(store, settings)

    if not tool.health_check():
        print("Calendar connector health check failed — check your .env and OAuth setup.")
        return

    print(f"Searching Calendar for: {query!r}\n")
    for event in tool.search_events(process_id="demo", query=query, max_results=5):
        print(f"- [{event.start} -> {event.end}] {event.title}")
        if event.attendees:
            print(f"    attendees: {', '.join(event.attendees)}")
        if event.location:
            print(f"    location: {event.location}")
        print()


if __name__ == "__main__":
    main()
