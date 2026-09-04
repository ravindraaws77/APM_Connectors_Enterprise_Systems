# APM Connectors & Enterprise Systems

The connector/enterprise-systems layer of the APM (Agentic Process
Management) project, extracted into its own standalone, shippable
service — Gmail, Google Calendar, and Excel connectors behind a plain
read/write HTTP API, plus a small LangGraph process that gates every
write behind explicit human approval.

> This package has **no reasoning of its own**. It's built to be
> plugged into any reasoning/orchestration layer — deployed separately
> — that decides what to read and what write to propose, then calls
> this API to actually do it.

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

- `docs/api-contract.md` — the `/tools/*` HTTP contract: every route,
  request/response shape, and the approval-gate flow.
- `docs/capability-map.md` — per-tool auth, capabilities, and known gaps.
- `docs/security-guardrails.md` — the non-negotiable rule: no write
  executes without an explicit human approval step.
- `docs/running-locally.md` — setup and how to run it.

## Layout

```
src/apm_connectors/
  config.py      env/config loading
  state/         persistent status + audit log store
  tools/         one module per external tool, common interface in base.py
  graph.py       the small propose -> approval -> execute LangGraph layer
  api/           FastAPI app exposing tools/graph over HTTP (/tools/*)
tests/           unit tests, runnable without live credentials
scripts/         manual smoke-test scripts for real credentials
.claude/skills/  tool-integration: the checklist for adding a connector
```
