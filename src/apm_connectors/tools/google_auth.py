"""Shared Google OAuth helper for the Gmail and Calendar connectors — they
use the same installed-app consent flow and can share a token cache.

This module only produces authorized credentials; it never touches
Gmail/Calendar data itself. Google's auth libraries are imported lazily
inside the function so the rest of the codebase (and any test that only
exercises a connector's logic with a fake client) doesn't need those
dependencies installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore

if TYPE_CHECKING:
    from apm_connectors.tools.calendar_tool import CalendarTool
    from apm_connectors.tools.gmail_tool import GmailTool

DEFAULT_TOKEN_PATH = Path(".google_token.json")


def load_credentials(
    settings: Settings,
    scopes: list[str],
    token_path: Path = DEFAULT_TOKEN_PATH,
):
    """Return authorized Google credentials for the given scopes, running
    the one-time browser consent flow if there's no cached token yet, or
    refreshing a cached token if it's expired.

    `token_path` is a local, gitignored file (see .gitignore's
    `*token*.json` pattern) — never commit it, it grants account access.

    Note on combining Gmail + Calendar: a cached token is only valid for
    the scopes it was originally consented to. Calling this with the
    Gmail scopes alone and later the Calendar scopes alone produces two
    separate consent prompts against the same token_path, and the second
    overwrites the first — the earlier tool then fails at request time
    with an insufficient-scope error, not at token-load time. Use
    `build_gmail_and_calendar_tools` (below) when you need both tools —
    it requests every scope in one call so one consent covers both.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not settings.google_client_id or not settings.google_client_secret:
                raise RuntimeError(
                    "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. "
                    "See .env.example for how to obtain them from Google "
                    "Cloud Console, then set them in your local .env."
                )
            client_config = {
                "installed": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def build_gmail_and_calendar_tools(
    state: StateStore, settings: Settings, token_path: Path = DEFAULT_TOKEN_PATH
) -> tuple["GmailTool", "CalendarTool"]:
    """Build both Google tools from a single OAuth consent covering both
    tools' scopes at once — this is the fix for the token-cache overwrite
    issue noted above: build_gmail_tool() and build_calendar_tool() each
    request only their own scopes, so calling them separately against the
    same token_path re-prompts for consent and each overwrites the
    other's cached token. apm_connectors.api.dependencies.get_tools()
    uses this function instead of the two single-tool factories whenever
    it needs both. Raises RuntimeError (via load_credentials) if
    GOOGLE_CLIENT_ID/SECRET aren't set — get_tools() catches that so a
    deployment with no Google account configured still gets Excel (or
    any other configured connector) rather than failing entirely.
    """
    from apm_connectors.tools.calendar_tool import (
        CALENDAR_EVENTS_SCOPE,
        CALENDAR_READONLY_SCOPE,
        CalendarTool,
        GoogleApiCalendarClient,
    )
    from apm_connectors.tools.gmail_tool import GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE, GmailTool, GoogleApiGmailClient

    scopes = [GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE, CALENDAR_READONLY_SCOPE, CALENDAR_EVENTS_SCOPE]
    credentials = load_credentials(settings, scopes=scopes, token_path=token_path)
    gmail_tool = GmailTool(state, GoogleApiGmailClient(credentials))
    calendar_tool = CalendarTool(state, GoogleApiCalendarClient(credentials))
    return gmail_tool, calendar_tool
