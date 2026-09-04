# Running locally

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -e ".[connectors]"
pytest -q
```

No credentials are needed to run the test suite — every connector is
tested against an in-memory fake client (see `tests/`).

## Run the API

```
uvicorn apm_connectors.api.app:app --reload --port 8000
```

Sanity check it's up:

```
python scripts/api_smoke_test.py
```

## Run the MCP server (for an LLM-based agent)

An alternative to a reasoning layer calling `/tools/*` directly over
HTTP: `apm_connectors_mcp` exposes the same routes as MCP tools, so an
LLM agent (Claude Desktop, Claude Code, any MCP-capable host) can call
them itself, using each tool's description as the vocabulary to
translate a free-text request into an actual call. Requires the API
above already running.

```
pip install -e ".[mcp]"
APM_CONNECTORS_BASE_URL=http://127.0.0.1:8000 apm-connectors-mcp
```

That starts a stdio-transport MCP server (the default for a local
agent host's MCP config, e.g. pointing Claude Desktop/Code at the
`apm-connectors-mcp` command). For a remote reasoning layer instead,
set `APM_CONNECTORS_MCP_TRANSPORT=sse` or `streamable-http`.

`tests/test_mcp_server.py` covers it the same way `test_tools_api.py`
covers the REST layer — fake tools, in-process, no live credentials or
running server needed; it's skipped automatically (see `conftest.py`)
if the `mcp` extra isn't installed.

## Configure real connectors

Copy `.env.example` to `.env` and fill in whichever tools you want to
exercise for real — see `docs/capability-map.md` for what each one
needs. Every route works with fake clients (tests) with no `.env` at
all; real credentials are only needed to actually call Gmail/Calendar/
Excel.

## What this service is (and isn't)

This is the connector/enterprise-systems layer only — see
`docs/api-contract.md` for the full `/tools/*` contract. There's no
reasoning, no free-text entry point, no dashboard here: a reasoning or
orchestration layer is expected to be a separate deployment that calls
this API directly, or through `apm_connectors_mcp` if it's an
LLM-based agent. See `docs/security-guardrails.md` for the one rule
that never bends regardless of who's calling: every write pauses for
human approval before anything executes.
