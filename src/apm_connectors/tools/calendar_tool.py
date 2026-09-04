"""Google Calendar connector.

Read (list/search events) has been available since phase 3. This phase
(5) adds create_event — the write/action capability deferred until now,
same reasoning as Gmail's send_email: only ever called with dry_run=False
from inside the agent graph's execute_node, after an approved interrupt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools._retry import with_retry
from apm_connectors.tools.base import ActionResult, BaseTool, Capability

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CalendarClient(Protocol):
    """The minimal surface CalendarTool needs from a Calendar API client.
    Both the real client (`GoogleApiCalendarClient`, below) and test
    fakes implement just this.
    """

    def list_events(
        self, time_min: str | None, time_max: str | None, query: str | None, max_results: int
    ) -> list[dict[str, Any]]: ...

    def get_event(self, event_id: str) -> dict[str, Any]: ...

    def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EventSummary:
    event_id: str
    title: str
    start: str | None
    end: str | None
    attendees: list[str]
    location: str | None


class CalendarTool(BaseTool):
    """Google Calendar connector: list/search/read events, and create an
    event — the latter only ever reachable through the agent's approval
    interrupt (see apm_connectors.agent.graph).
    """

    name = "google_calendar"
    capabilities = frozenset({Capability.READ, Capability.ACTION})

    def __init__(self, state: StateStore, client: CalendarClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            self._client.list_events(time_min=None, time_max=None, query=None, max_results=1)
            return True
        except Exception:
            return False

    def search_events(
        self,
        process_id: str,
        query: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
    ) -> list[EventSummary]:
        """List/search events, optionally filtered by a free-text query
        and/or an RFC3339 time window (e.g. `time_min="2026-09-01T00:00:00Z"`).
        """
        raw_events = self._client.list_events(
            time_min=time_min, time_max=time_max, query=query, max_results=max_results
        )
        summaries = [self._to_summary(e) for e in raw_events]
        self._log(
            process_id,
            "read",
            f"Searched Calendar (query={query!r}), found {len(summaries)} event(s)",
            {"query": query, "time_min": time_min, "time_max": time_max, "count": len(summaries)},
        )
        return summaries

    def read_event(self, process_id: str, event_id: str) -> EventSummary:
        summary = self._to_summary(self._client.get_event(event_id))
        self._log(
            process_id,
            "read",
            f"Read Calendar event '{summary.title}'",
            {"event_id": event_id},
        )
        return summary

    def create_event(
        self,
        process_id: str,
        title: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        location: str | None = None,
        dry_run: bool = True,
    ) -> ActionResult:
        """Create a single (non-recurring) event. `start`/`end` are
        RFC3339 datetimes (e.g. "2026-09-10T15:00:00Z"). Only ever call
        this with dry_run=False from inside the agent graph, after the
        human-approval interrupt has returned an approval.
        """
        summary = f"Create Calendar event '{title}' at {start}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        payload = {
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "attendees": [{"email": a} for a in (attendees or [])],
        }
        if location:
            payload["location"] = location

        if dry_run:
            return ActionResult(executed=False, description=summary, details=payload)

        created = self._client.insert_event(payload)
        return ActionResult(
            executed=True,
            description=summary,
            details={**payload, "event_id": created.get("id")},
        )

    @staticmethod
    def _to_summary(raw: dict[str, Any]) -> EventSummary:
        start = raw.get("start", {})
        end = raw.get("end", {})
        return EventSummary(
            event_id=raw["id"],
            title=raw.get("summary", "(no title)"),
            start=start.get("dateTime") or start.get("date"),
            end=end.get("dateTime") or end.get("date"),
            attendees=[a.get("email", "") for a in raw.get("attendees", [])],
            location=raw.get("location"),
        )


class GoogleApiCalendarClient:
    """Real Calendar API client, built from OAuth credentials obtained via
    apm_connectors.tools.google_auth.load_credentials. Imports googleapiclient
    lazily so this module — and CalendarTool's unit tests, which use a
    fake client — don't require that dependency at import time.
    """

    def __init__(self, credentials: Any, calendar_id: str = "primary") -> None:
        from googleapiclient.discovery import build

        self._service = build("calendar", "v3", credentials=credentials)
        self._calendar_id = calendar_id

    @with_retry()
    def list_events(
        self, time_min: str | None, time_max: str | None, query: str | None, max_results: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "calendarId": self._calendar_id,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query
        response = self._service.events().list(**params).execute()
        return response.get("items", [])

    @with_retry()
    def get_event(self, event_id: str) -> dict[str, Any]:
        return self._service.events().get(calendarId=self._calendar_id, eventId=event_id).execute()

    # Deliberately NOT retried -- see apm_connectors.tools._retry's module docstring:
    # a dropped connection after the server already created the event
    # must not turn into an automatic duplicate.
    def insert_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service.events().insert(calendarId=self._calendar_id, body=payload).execute()


def build_calendar_tool(state: StateStore, settings: Settings) -> CalendarTool:
    """Convenience factory: runs the OAuth flow (if needed) and returns a
    CalendarTool backed by the real Calendar API. Shares the same token
    cache as build_gmail_tool if both scopes are requested together —
    see apm_connectors.tools.google_auth.
    """
    from apm_connectors.tools.google_auth import load_credentials

    credentials = load_credentials(settings, scopes=[CALENDAR_READONLY_SCOPE, CALENDAR_EVENTS_SCOPE])
    return CalendarTool(state, GoogleApiCalendarClient(credentials))
