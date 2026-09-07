"""Pydantic request/response models for the connector API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DecisionRequest(BaseModel):
    approved: bool


class RunOutcomeResponse(BaseModel):
    """Mirrors apm_connectors.graph.RunOutcome. Exactly one of
    pending_action / final_result is set: pending_action means the graph
    is paused waiting for a POST to /tools/actions/{action_id}/decision;
    final_result means it's done.

    action_id is always present, whether the caller supplied a
    process_id on the propose call or not (see the request models
    below) -- it's the value to relay back on the decision call, not
    something the caller needs to have chosen in advance.
    """

    action_id: str
    summary: str | None
    pending_action: dict[str, Any] | None
    final_result: dict[str, Any] | None


# -- /tools/* request models ---------------------------------------------
# One field per keyword argument the matching apm_connectors.tools method
# takes, plus an optional process_id. No reasoning here: a caller
# supplies exactly the read it wants, or the write it wants proposed.
#
# process_id is entirely optional: a calling agent won't generally have
# an internal APM process/case id to hand, and shouldn't need one just
# to call a connector. It only exists as an audit-trail grouping label
# (StateStore.log_event) -- pass one if you want related calls to show
# up together under GET /processes/{id}/history; omit it and the server
# generates one internally per call so every call still gets logged.
# For a write, the id actually used (yours or generated) comes back as
# RunOutcomeResponse.action_id -- that's the id to relay to
# POST /tools/actions/{action_id}/decision, not process_id itself.


class GmailSearchRequest(BaseModel):
    process_id: str | None = None
    query: str
    max_results: int = 10


class GmailReadRequest(BaseModel):
    process_id: str | None = None
    message_id: str


class GmailSendRequest(BaseModel):
    process_id: str | None = None
    to: str
    subject: str
    body: str


class CalendarSearchRequest(BaseModel):
    process_id: str | None = None
    query: str | None = None
    time_min: str | None = None
    time_max: str | None = None
    max_results: int = 10


class CalendarReadRequest(BaseModel):
    process_id: str | None = None
    event_id: str


class CalendarCreateEventRequest(BaseModel):
    process_id: str | None = None
    title: str
    start: str
    end: str
    attendees: list[str] | None = None
    location: str | None = None


class ExcelWorksheetsRequest(BaseModel):
    process_id: str | None = None


class ExcelReadRequest(BaseModel):
    process_id: str | None = None
    sheet_name: str | None = None
    address: str | None = None


class ExcelWriteRequest(BaseModel):
    process_id: str | None = None
    sheet_name: str
    address: str
    values: list[list[Any]]


class SalesforceQueryRequest(BaseModel):
    process_id: str | None = None
    soql: str


class SalesforceReadRequest(BaseModel):
    process_id: str | None = None
    object_name: str
    record_id: str


class SalesforceCreateRequest(BaseModel):
    process_id: str | None = None
    object_name: str
    fields: dict[str, Any]


class SalesforceUpdateRequest(BaseModel):
    process_id: str | None = None
    object_name: str
    record_id: str
    fields: dict[str, Any]
