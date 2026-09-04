# Security, guardrails & trust — connector layer baseline

Adapted from the original APM MVP's `security_guardrails_trust_overview.pdf`
(Workstream 5) baseline for this package's scope: the connector layer and
its approval-gated write API. This is a starting baseline, not the full
target state.

## 1. Access & permissions
- Every tool connector declares its own OAuth scopes explicitly; request
  the minimum scope needed (e.g. `gmail.readonly` before `gmail.send`).
- Credentials are per-user (your own Google/Microsoft account), never a
  shared service account, for this MVP.

## 2. Credential & secret management
- Secrets live only in a local `.env` file (or your OS keychain/OAuth token
  cache) — never in code, never committed. `.env.example` documents the
  required variable names with no real values.
- `.gitignore` blocks `.env`, `*token*.json`, `credentials.json`, and
  `client_secret*.json` by pattern, as a backstop against accidental commits.

## 3. Data protection
- No email/calendar/spreadsheet content is persisted beyond what's needed
  to show the current process status — the state store keeps summaries and
  action records, not full raw payloads, wherever practical.

## 4. Auditability & traceability
- Every tool call (read or write) and every approval decision is appended
  to the audit log in `src/apm_connectors/state/store.py`: who/what
  proposed it, what it was, the decision, and the outcome. Logs are
  append-only from the application's perspective.

## 5. The core guardrail: human approval before any write/send/action

**This is the non-negotiable rule for this package:** a tool's `read`
capability can run whenever a caller needs it. A tool's `write` or
`action` capability can **only** run after an explicit human decision
(`POST /tools/actions/{action_id}/decision`, `approved: true` — see
`docs/api-contract.md`). There is no code path here that sends an email,
creates a calendar event, or writes a spreadsheet row without that step.
This is implemented, not aspirational: `src/apm_connectors/graph.py`'s
`execute_node` is the only place any tool's write/action method is ever
called with `dry_run=False`, and it only runs after `approval_node`'s
`interrupt()` has returned an approved decision — the graph physically
pauses and checkpoints state at that point, it isn't a soft "best effort"
check, execution cannot continue without a `Command(resume=...)` signal.
This holds regardless of what decided the action was worth proposing —
this package makes no assumption about, and has no dependency on, the
reasoning/orchestration layer that calls it.

Every connector also supports a `dry_run` mode: report exactly what a
write/action call *would* do without doing it, used for local testing
before real credentials are wired up.

**Human approval is necessary but not sufficient on its own** — found in
practice in the original APM MVP this package was extracted from: a
caller once proposed sending to a fabricated `customer@example.com`
address with no real customer address anywhere in the underlying data,
and a human approver had no way to recognize that address as fake at a
glance rather than a real domain they simply didn't recognize. The fix
lives at this layer, not the caller's: `GmailTool.send_email` hard-refuses
any RFC 2606 reserved/placeholder domain (`example.com`, anything under
`.test`/`.example`/`.invalid`/`.localhost`, etc.) regardless of `dry_run`
or approval status — a guarantee, since it doesn't depend on whatever
decided to propose the send in the first place.

## 6. Least privilege in practice for this MVP
- Start every new tool integration read-only; add write/action scopes only
  once the read path is reviewed and working.
- There is intentionally no "autonomous mode" flag anywhere in this
  package — every write, from any caller, goes through the approval gate.
