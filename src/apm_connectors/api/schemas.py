"""Pydantic request/response models for the connector API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DecisionRequest(BaseModel):
    approved: bool


class RunOutcomeResponse(BaseModel):
    """Mirrors apm_connectors.graph.RunOutcome. Exactly one of
    pending_action / final_result is set: pending_action means the graph
    is paused waiting for a POST to /tools/actions/{id}/decision;
    final_result means it's done.
    """

    process_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None


# -- /tools/* request models ---------------------------------------------
# One field per keyword argument the matching apm_connectors.tools method
# takes, plus process_id (every tool method needs one, for the audit
# trail). No reasoning here: a caller supplies exactly the read it
# wants, or the write it wants proposed.


class GmailSearchRequest(BaseModel):
    process_id: str
    query: str
    max_results: int = 10


class GmailReadRequest(BaseModel):
    process_id: str
    message_id: str


class GmailSendRequest(BaseModel):
    process_id: str
    to: str
    subject: str
    body: str


class CalendarSearchRequest(BaseModel):
    process_id: str
    query: str | None = None
    time_min: str | None = None
    time_max: str | None = None
    max_results: int = 10


class CalendarReadRequest(BaseModel):
    process_id: str
    event_id: str


class CalendarCreateEventRequest(BaseModel):
    process_id: str
    title: str
    start: str
    end: str
    attendees: list[str] | None = None
    location: str | None = None


class ExcelWorksheetsRequest(BaseModel):
    process_id: str


class ExcelReadRequest(BaseModel):
    process_id: str
    sheet_name: str | None = None
    address: str | None = None


class ExcelWriteRequest(BaseModel):
    process_id: str
    sheet_name: str
    address: str
    values: list[list[Any]]
