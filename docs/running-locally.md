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
tested against an in-memory fake client (see `tests/`). `pytest -q`
above also runs `tests/integration/`: the same fake-client coverage,
but driven over real HTTP against a real running server process
(`uvicorn`/`socket`, no live credentials) rather than FastAPI's
in-process `TestClient` — run just that suite with
`pytest tests/integration -q`.

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

## Durable state (optional: Postgres)

By default, status/audit state lives in a local JSON file and paused
(proposed-but-not-yet-approved) actions live in memory — zero extra
infra, but both are lost on restart. Set `DATABASE_URL` (see
`.env.example`) to swap in `PostgresStateStore` and a Postgres-backed
LangGraph checkpointer instead (`src/apm_connectors/state/postgres_store.py`,
`src/apm_connectors/api/dependencies.py`), so that state survives a
restart or redeploy — see `docs/deployment.md`'s "State is ephemeral"
note for why this matters for a real deployment. Needs the optional
`postgres` extra:

```
pip install -e ".[connectors,postgres]"
```

Tables (`apm_processes`, `apm_events`, `apm_pending_actions`, plus the
checkpointer's own `checkpoint*` tables) are created automatically on
first use — no separate migration step.

`tests/test_postgres_state_store.py` and
`tests/test_postgres_checkpointer.py` exercise this against a real
Postgres; they're skipped automatically unless both the `postgres`
extra is installed and `APM_TEST_DATABASE_URL` points at a real,
reachable (and disposable — tests truncate its tables) database:

```
createdb apm_test
APM_TEST_DATABASE_URL=postgresql://localhost/apm_test pytest tests/test_postgres_state_store.py tests/test_postgres_checkpointer.py -q
```

## What this service is (and isn't)

This is the connector/enterprise-systems layer only — see
`docs/api-contract.md` for the full `/tools/*` contract. There's no
reasoning, no free-text entry point, no dashboard here: a reasoning or
orchestration layer is expected to be a separate deployment that calls
this API directly, or through `apm_connectors_mcp` if it's an
LLM-based agent. See `docs/security-guardrails.md` for the one rule
that never bends regardless of who's calling: every write pauses for
human approval before anything executes.

See `docs/deployment.md` to run this same API as a container, either
locally with Docker or deployed to AWS App Runner.
