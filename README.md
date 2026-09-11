# APM Connectors & Enterprise Systems

The connector/enterprise-systems layer of the APM (Agentic Process
Management) project, extracted into its own standalone, shippable
service — Gmail, Google Calendar, Excel, Salesforce, and Jira
connectors behind a plain read/write HTTP API, plus a small LangGraph
process that gates every write behind explicit human approval.

> This package has **no reasoning of its own**. It's built to be
> plugged into any reasoning/orchestration layer — deployed separately
> — that decides what to read and what write to propose, then calls
> this API to actually do it. `apm_connectors_mcp` (below) is one such
> way to plug it into an LLM-based agent: an MCP server exposing every
> `/tools/*` route as an agent tool, over the same HTTP contract.

## Why this exists

Extracted from the main [APM MVP repo](https://github.com/ravindraaws77/AIAGENT_APM)
once its integration layer was solid enough to stand on its own: a
clean HTTP contract for the tools layer, decoupled from any specific
reasoning engine, dashboard, or voice interface, so it can be a
dependency of more than one consumer.

## Quick start

```
pip install -e ".[connectors]"
pytest -q
uvicorn apm_connectors.api.app:app --reload --port 8000
python scripts/api_smoke_test.py
```

See `docs/running-locally.md` for the full walkthrough.

## Docs

- `docs/architecture.md` — system-level view: components, the
  propose/approve/execute flow, persistence, and deployment topology.
  Start here if you're new to the repo. `docs/architecture.pdf` is a
  single-page, at-a-glance version of the same system as one flowchart.
- `docs/api-contract.md` — the `/tools/*` HTTP contract: every route,
  request/response shape, and the approval-gate flow.
- `docs/capability-map.md` — per-tool auth, capabilities, and known gaps.
- `docs/security-guardrails.md` — the non-negotiable rule: no write
  executes without an explicit human approval step.
- `docs/running-locally.md` — setup and how to run it, including the
  MCP server.
- `docs/deployment.md` — deploying the API to AWS ECS on Fargate via
  Terraform (`infra/aws/ecs-fargate/`), and running the integration
  test suite against a real running server.
- `docs/team-quickstart.md` — for anyone consuming a running instance
  of this API: another APM layer, a script, or Claude via
  `apm_connectors_mcp`.
- `docs/google-account-setup.md` — pointing the Gmail/Calendar
  connectors at a different Google account, locally or on the AWS
  deployment.

Durable state (swapping the default file-backed/in-memory status,
audit log, and paused-approval storage for Postgres) is covered inline
in `docs/running-locally.md` ("Durable state") and `docs/deployment.md`
("Enabling durable state") rather than its own doc — see
`src/apm_connectors/state/postgres_store.py` for the implementation.

## Layout

```
src/apm_connectors/
  config.py      env/config loading
  state/         status + audit log store -- file-backed by default,
                 Postgres-backed via DATABASE_URL (postgres_store.py)
  tools/         one module per external tool, common interface in base.py
  graph.py       the small propose -> approval -> execute LangGraph layer
  api/           FastAPI app exposing tools/graph over HTTP (/tools/*)
src/apm_connectors_mcp/
  client.py      thin async HTTP client for the /tools/* API above
  server.py      MCP server: one tool per /tools/* route, for an LLM agent
tests/               unit tests, runnable without live credentials
tests/integration/   full-stack tests against a real running server, also no live credentials
scripts/         manual smoke-test scripts for real credentials
infra/aws/       Terraform to deploy the API to AWS ECS on Fargate
.claude/skills/  tool-integration: the checklist for adding a connector
```
