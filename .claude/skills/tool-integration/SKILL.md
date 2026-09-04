---
name: tool-integration
description: Use when adding, changing, or reviewing a connector to an external tool/system (Gmail, Calendar, Excel, or any future tool) in this repo. Ensures the read-before-write ordering, approval gating, dry-run support, and capability-map documentation stay consistent across connectors.
---

# Adding a tool connector

This package's core guardrail is: **read capabilities may run freely; write or
action capabilities may only run after explicit human approval.** This
skill is the checklist for adding a connector without breaking that.

## Steps

1. **Read first.** Implement and land the read/search capability before
   any write/action capability, even if the same PR could technically
   include both. This matches the workstream's own phase ordering and lets
   the read path be reviewed in isolation.

2. **Implement the common interface** (`src/apm_connectors/tools/base.py`):
   - Declare `capabilities` as a set drawn from `{"read", "write", "action"}`.
   - Every public method that performs a `write`/`action` call must accept
     a `dry_run: bool` parameter (default `True`) and, when `True`, return a
     description of what would happen instead of doing it.
   - Every public method — read or write — logs to the state store
     (`src/apm_connectors/state/store.py`) via its audit helper, including on failure.

3. **Never let a write/action method execute unattended.** In the action
   graph (`src/apm_connectors/graph.py`), any node that calls a `write`/
   `action` method must be preceded by a LangGraph `interrupt()` (or
   equivalent explicit approval check if called outside the graph, e.g.
   from a test harness or CLI). Do not add a flag or config option that
   bypasses this for "production" or "trusted" use — if autonomous
   execution is needed later, that's a deliberate, separate design
   decision, not a default.

4. **Credentials belong in `.env`, never in code.** Add any new required
   variable names to `.env.example` with a placeholder value and a comment
   explaining where to obtain it (e.g. "Google Cloud Console → OAuth
   client ID"). Update `.gitignore` if the credential takes a new file
   form (e.g. a new token cache filename pattern).

5. **Update `docs/capability-map.md`** with a row for the tool: auth
   method, what's readable, what's writable/actionable, the recommended
   connection path, and any known gaps or blockers. This is a standing
   deliverable for the Agent Tools & Connectivity workstream, not a
   one-time note.

6. **Write at least one test that runs without live credentials** — using
   `dry_run=True` and/or a mocked client — so the connector's logic is
   verifiable in CI/locally without anyone's real Gmail/Calendar/Excel
   account.

## Anti-patterns to reject in review

- A write/action call with no `dry_run` path.
- A write/action call reachable from the action graph without an
  `interrupt()` upstream of it.
- Secrets (API keys, OAuth client secrets, tokens) hardcoded or committed,
  even in a test fixture.
- A connector with no corresponding row in `docs/capability-map.md`.
- Broad OAuth scopes requested "just in case" instead of the narrowest
  scope the current capability needs.
