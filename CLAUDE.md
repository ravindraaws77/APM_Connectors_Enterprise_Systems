# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## What this project is

The connector/enterprise-systems layer of APM (Agentic Process
Management), extracted from the main APM MVP repo
(`ravindraaws77/AIAGENT_APM`) to ship standalone. See `README.md` and
`docs/api-contract.md` for the full picture.

## Non-negotiable rule

**No tool call that writes, sends, or creates anything in a real external
system may execute without an explicit human approval step.** Read-only
calls are always fine. See `docs/security-guardrails.md`. When adding or
touching a tool connector, use the `tool-integration` skill in
`.claude/skills/`.

This package has no reasoning of its own — don't add one. If a request
implies "decide what to do," that decision belongs in a separate
reasoning/orchestration layer calling this API, not in this repo.

## Working conventions

- Never commit secrets. `.env.example` documents required variables;
  real values go in a local, gitignored `.env`.
- Every tool connector implements the common interface in
  `src/apm_connectors/tools/base.py` and is registered in
  `docs/capability-map.md`.
- Every action (read, proposed write, approval, rejection, execution,
  failure) is recorded via the state store (`src/apm_connectors/state/
  store.py`'s `StateStoreProtocol`) — file-backed by default,
  Postgres-backed (`state/postgres_store.py`) when `DATABASE_URL` is
  set. Callers only ever depend on the method surface, never on which
  one is behind it.
- Prefer dry-run-testable code: a connector should be exercisable with
  `dry_run=True` and no live credentials, so its logic can be reviewed and
  tested before anyone wires up real accounts.
- Adding a new tool or a new read/write route is additive; changing an
  existing `/tools/*` route's request/response shape is a breaking
  change for whatever's already built against `docs/api-contract.md`.

## Reference documents

When asked for an architecture doc, or a similarly detailed reference
doc for one layer (e.g. deployment/Terraform, MCP server), use the
tooling in `scripts/docs/` — read `scripts/docs/README.md` first. It
has the shared ReportLab template (`_pdf_template.py`), a worked
example (`gen_mcp_server_pdf.py` → `docs/mcp-server-reference.pdf`),
and the two document shapes in use (text-only deep dive vs. diagram +
reference + deep dive, the latter used for `docs/architecture.pdf`).
Rebuild from the current source (`git pull` first) rather than editing
stale prose, and render every generated page to an image and look at
it before calling a doc done — layout bugs (clipped text, overflow)
are easy to introduce and easy to catch that way; scripts/docs/README.md
has the exact snippet.

## Layout

```
docs/            architecture, api contract, capability map, security guardrails, running locally, deployment
.claude/skills/  tool-integration: checklist for adding a connector
src/apm_connectors/
  config.py      env/config loading
  state/         status + audit log store -- file-backed by default,
                 Postgres-backed via DATABASE_URL (postgres_store.py)
  tools/         one module per external tool, common interface in base.py
  graph.py       small propose -> approval -> execute LangGraph layer
  api/           FastAPI app + /tools/* routes
tests/               unit tests, runnable without live credentials
tests/integration/   full-stack tests against a real running server, also no live credentials
scripts/         manual smoke-test scripts for real credentials
infra/aws/       Terraform to deploy the API to AWS ECS on Fargate
```
