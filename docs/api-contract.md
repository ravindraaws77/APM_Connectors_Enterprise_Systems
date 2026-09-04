# Connector API contract — `/tools/*`

This is the stable contract this package exposes over HTTP
(`src/apm_connectors/api/tools_routes.py`, mounted by
`src/apm_connectors/api/app.py`). It's written for whatever consumes
it — a reasoning/orchestration layer, a script, an agent framework —
deployed separately from this package. This package has **no reasoning
of its own**: no free-text entry point, no LLM call anywhere in this
process. A caller decides exactly what to read and what write to
propose; this package only executes reads, gates writes behind human
approval, and keeps the audit trail.

For the Python-level connector contract (how to add or change a
connector, `dry_run`, capability flags) see
`.claude/skills/tool-integration/SKILL.md` and
`src/apm_connectors/tools/base.py`. For per-tool auth/setup/known gaps,
see `docs/capability-map.md`. This doc is the HTTP surface only.

## Base URL

Wherever `uvicorn apm_connectors.api.app:app` is running, e.g.
`http://127.0.0.1:8000` locally. See `docs/running-locally.md`.

## Conventions that hold for every route below

- **`process_id` is optional on every call** (read or write). It's only
  an audit-trail grouping label (`StateStore.log_event`), not something
  a caller has to look up or invent first — a calling agent generally
  won't have an internal APM process/case id to hand, and doesn't need
  one just to call a connector. Pass one if you *do* want related calls
  to show up together under `GET /processes/{id}/history` (e.g. reusing
  `"order-4521"` across a whole business case); omit it and the server
  generates one internally per call so it's still logged, just not
  grouped with anything else. **For a write**, don't confuse this with
  the id you need for the decision call below — that one always comes
  back from the server as `action_id`, whether you passed a
  `process_id` or not.
- **Reads execute immediately** and return the tool's data directly, no
  approval step — read is always allowed.
- **Writes never execute immediately.** Every write route returns a
  `RunOutcomeResponse` with `pending_action` set and `final_result:
  null` — the action is recorded but not run. Nothing happens in the
  real system until a human decision arrives via the matching decision
  route. This is the one non-negotiable rule of this package, enforced
  at the connector layer (`BaseTool.require_dry_run_guard`) as well as
  here — there is no flag or parameter anywhere in this API that skips
  it.
- **Errors:**
  - `503` — the tool isn't configured on this server (e.g. no
    `APM_EXCEL_WORKBOOK_PATH` set). Returned before anything is
    recorded — a write call that 503s creates no pending action.
  - `502` — the tool call itself failed (a network error, an exhausted
    retry, an upstream API error). `detail` carries a readable message;
    the server logs the full traceback.
  - `422` — the request body didn't match the schema (standard FastAPI
    validation).
- **No auth today.** This API assumes a trusted internal caller — an
  API key/bearer check before exposing this beyond a network boundary
  it doesn't already trust is a known, separate piece of work, not yet
  done.

## Gmail

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/gmail/search` | read | `{process_id?, query, max_results?: 10}` | `[{message_id, thread_id, sender, subject, snippet, received_at}, ...]` |
| `POST /tools/gmail/read` | read | `{process_id?, message_id}` | `{message_id, thread_id, sender, subject, snippet, received_at}` |
| `POST /tools/gmail/send` | **write** | `{process_id?, to, subject, body}` | `RunOutcomeResponse` (see below) |

`query` uses Gmail's search syntax (e.g. `"from:customer@example.com
newer_than:14d"`). `send` refuses outright — even after approval — if
`to` is an RFC 2606 reserved/placeholder domain (`example.com` and
similar); see `gmail_tool.py`'s `RESERVED_PLACEHOLDER_DOMAINS`.

## Google Calendar

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/calendar/search` | read | `{process_id?, query?, time_min?, time_max?, max_results?: 10}` | `[{event_id, title, start, end, attendees, location}, ...]` |
| `POST /tools/calendar/read` | read | `{process_id?, event_id}` | `{event_id, title, start, end, attendees, location}` |
| `POST /tools/calendar/create-event` | **write** | `{process_id?, title, start, end, attendees?, location?}` | `RunOutcomeResponse` |

`start`/`end` are RFC3339 datetimes (e.g. `"2026-09-10T15:00:00Z"`).
Only single, non-recurring events — no recurrence support.

## Excel (local file or Google Drive `.xlsx`)

| Route | Kind | Request body | Returns |
|---|---|---|---|
| `POST /tools/excel/worksheets` | read | `{process_id?}` | `["Sheet1", "Renewals", ...]` |
| `POST /tools/excel/read` | read | `{process_id?, sheet_name?, address?}` | `{sheet_name, address, values: [[...], ...]}` |
| `POST /tools/excel/write` | **write** | `{process_id?, sheet_name, address, values: [[...], ...]}` | `RunOutcomeResponse` |

One workbook per running server (`APM_EXCEL_WORKBOOK_PATH` or
`APM_EXCEL_DRIVE_FILE_ID` — see `docs/capability-map.md`); if neither
is set, every Excel route 503s. `read`'s `sheet_name`/`address` default
to the workbook's first worksheet and its whole used range when
omitted — pass them explicitly for anything more specific.

## Approving or rejecting a write

Every write route above returns a paused `RunOutcomeResponse`. Its
`action_id` is the id to use for the decision call — the server
generated it here because this example's `/tools/gmail/send` call
didn't pass a `process_id`; had it passed one, `action_id` would be
that value instead. Either way, the caller takes `action_id` from
*this* response — it's never something to construct or guess in
advance:

```json
{
  "action_id": "3f0a9e21-6b7a-4e3d-9c0e-2a5f6d8b1c44",
  "summary": null,
  "pending_action": {
    "type": "approval_request",
    "action_id": "…",
    "tool": "gmail",
    "method": "send_email",
    "description": "Send email to customer@realcorp.io: 'Update'",
    "payload": {"to": "customer@realcorp.io", "subject": "Update", "body": "…"},
    "category": "manual"
  },
  "final_result": null
}
```

Resolve it with:

```
POST /tools/actions/{action_id}/decision
{"approved": true}
```

On approval, the response's `final_result` is set (`pending_action:
null`):

```json
{
  "action_id": "3f0a9e21-6b7a-4e3d-9c0e-2a5f6d8b1c44",
  "summary": null,
  "pending_action": null,
  "final_result": {
    "executed": true,
    "description": "Send email to customer@realcorp.io: 'Update'",
    "details": {"to": "customer@realcorp.io", "subject": "Update", "message_id": "…"}
  }
}
```

On rejection: `final_result: {"executed": false, "reason": "rejected"}`
— nothing was sent/created/written.

## Worked example (Gmail send)

Without a `process_id` — the common case for a calling agent that has
no APM-internal id to give:

```
POST /tools/gmail/search
{"query": "newer_than:14d order 4521"}
→ 200, list of matching emails

POST /tools/gmail/send
{"to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."}
→ 200, pending_action set, action_id: "3f0a9e21-…" — nothing sent yet

...human approves...

POST /tools/actions/3f0a9e21-…/decision
{"approved": true}
→ 200, final_result.executed == true — now it's actually sent
```

With a `process_id` — when the caller *does* want related calls
grouped under one audit-trail thread (e.g. a reasoning layer that
tracks its own case ids and wants them to double as the APM one):

```
POST /tools/gmail/search
{"process_id": "order-4521", "query": "newer_than:14d order 4521"}
→ 200, list of matching emails

POST /tools/gmail/send
{"process_id": "order-4521", "to": "customer@realcorp.io", "subject": "Update", "body": "Your order is delayed."}
→ 200, pending_action set, action_id: "order-4521" (echoes process_id back verbatim)

...human approves...

POST /tools/actions/order-4521/decision
{"approved": true}
→ 200, final_result.executed == true
```

`GET /processes/{id}/history` and `GET /processes/{id}/pending` work
the same for any id — whichever `process_id`/`action_id` string ended
up being used, caller-supplied or generated — since the audit trail and
pending-action store are shared infrastructure
(`src/apm_connectors/state/store.py`).

## Stability

Treat this as the contract a reasoning/orchestration layer codes
against: request/response shapes here
(`src/apm_connectors/api/schemas.py`) shouldn't change casually. Adding
a new tool or a new read/write method is additive and safe; changing an
existing route's request/response shape is a breaking change for
anything already built against it.
