# Capability map — per-tool reference

Extracted from the original APM MVP's Workstream 2 capability map,
trimmed to this package's actual scope: the connectors and their HTTP
surface, not the reasoning/UI layer that used to sit on top of them in
the source repo (references to a reasoner, an intent parser, or a
dashboard below don't apply here — see `docs/api-contract.md` for what
this package actually exposes).

| Tool | Auth | Read/retrieve | Write/action | Known gaps / blockers |
|---|---|---|---|---|
| **Gmail** | Google OAuth 2.0 (user consent) | Search/list messages, read message content and metadata — `src/apm_connectors/tools/gmail_tool.py` (`GmailTool.search_emails`/`read_message`) | Send an email (`send_email`) — only ever called with `dry_run=False` from `apm_connectors.graph`'s `execute_node`, after an approved `interrupt()`; hard-refuses RFC 2606 reserved/placeholder recipient domains regardless of approval. Draft/apply-labels unimplemented. | Needs a Google Cloud OAuth client (see `.env.example`). Requests both `gmail.readonly` and `gmail.send` scopes. The default consent flow (`google_auth.load_credentials`) opens a browser and needs a local machine to catch the redirect — for a headless deployment (e.g. `infra/aws/ecs-fargate/`), generate a token locally once and set `GOOGLE_TOKEN_JSON` instead (see `.env.example`). |
| **Google Calendar** | Google OAuth 2.0 (same consent screen as Gmail, shared scopes via `google_auth.build_gmail_and_calendar_tools`) | List/search events, read attendees/times/location — `src/apm_connectors/tools/calendar_tool.py` | Create a single event (`create_event`) — same approval-gated pattern as Gmail's send. Update-event/respond-to-invite unimplemented. | Single, non-recurring events only — no timezone/recurrence handling. Same `GOOGLE_TOKEN_JSON` headless-deployment note as Gmail above (shared consent). |
| **Excel files (local + Google Drive)** — the default Excel connector, built by `get_tools()` | Local: none. Google Drive: Google OAuth 2.0, full `drive` scope (same client as Gmail/Calendar, separate token cache) | List worksheets, read a cell range — `src/apm_connectors/tools/excel_file_tool.py` (`ExcelFileTool.list_worksheets`/`read_range`) | Overwrite a cell range (`write_range`) — same dry-run-gated pattern. | Local source needs no credentials. Drive source only handles an actual `.xlsx` file, not a native Google Sheet. One workbook per running server (`APM_EXCEL_WORKBOOK_PATH` or `APM_EXCEL_DRIVE_FILE_ID`, at most one — see `.env.example`); if neither is set, every `/tools/excel/*` route 503s. `read_range` loads with `data_only=True`, so a formula cell never opened in real Excel/Sheets reads back as `None`. |
| **MS Excel (Microsoft Graph)** — *not wired into `get_tools()`* | Microsoft identity platform (Azure AD app registration), MSAL device-code flow | List worksheets, read a cell range — `src/apm_connectors/tools/excel_tool.py` | Overwrite a cell range (`write_range`) — same approval-gated pattern. | Needs a separate Azure AD app registration (why "Excel files" above, not this, is the default). Workbook must already be on OneDrive/SharePoint. Reachable via `scripts/excel_demo.py` directly, not through the API — onboarding it there needs a `build_configured_ms_excel_tool`-equivalent factory in `api/dependencies.py`, mirroring the Excel-files one. |
| **Salesforce** — *Connector_Enterprise, wired into `get_tools()`/the `/tools/*` API and the MCP server* | OAuth 2.0 **Client Credentials Flow** against a Connected App (`SALESFORCE_CLIENT_ID`/`SALESFORCE_CLIENT_SECRET`/`SALESFORCE_DOMAIN`) — server-to-server, no interactive login or redirect URI, deliberately not the older Username-Password OAuth flow (deprecated by Salesforce) | SOQL query (`query_records`) and read a single record by id (`get_record`) — `src/apm_connectors/tools/salesforce_tool.py`; exposed as `POST /tools/salesforce/query` and `POST /tools/salesforce/read` | Create a record (`create_record`) and update a record's fields (`update_record`) — same dry-run-gated, approval-interrupt-only pattern as every other connector's write/action methods; exposed as `POST /tools/salesforce/create` and `POST /tools/salesforce/update`, both gated the same way Gmail's `send`/Excel's `write` are | Needs a Salesforce admin to create a Connected App with Client Credentials Flow enabled and a "Run As" user assigned (that user's object/field permissions bound the connector's real-world reach — scope it narrowly, not org-wide). `build_configured_salesforce_tool` returns `None` when unconfigured (same "the API stays up, only this tool's routes 503" spirit as Excel's factory), so `/tools/salesforce/*` degrades cleanly with no Salesforce credentials set. Client Credentials access tokens are short-lived and cheap to re-request, so unlike the MS Graph connector's device-code flow there is no local token cache file to manage. Query results are capped by the caller's own SOQL `LIMIT` clause — this first pass does not follow Salesforce's `nextRecordsUrl` pagination for very large result sets. |

## Common tool interface

Every connector implements the same shape (see
`src/apm_connectors/tools/base.py`) so the API layer doesn't need
tool-specific code beyond routing:

- `capabilities`: which of `read`, `write`, `action` this tool supports
- `dry_run`: when true, a write/action call returns what *would* happen
  without doing it — used for local testing without live credentials
- every call is written to the audit log in
  `src/apm_connectors/state/store.py`, whether it was a read, a proposed
  write, an approval, a rejection, or an executed action
