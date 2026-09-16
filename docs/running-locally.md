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

## Durable state (Postgres, required)

The API server's status/audit store and its LangGraph action-graph
checkpointer are both Postgres-only — no file-backed/SQLite/in-memory
fallback (mirroring apm_orchestrator's own Postgres-only case-graph
checkpointer, which its `poller.py`/`scripts/run_case.py` also refuse
to run without a `DATABASE_URL`). Set it, and install the optional
`postgres` extra, before starting the server below:

```
pip install -e ".[connectors,postgres]"
createdb apm_dev   # or point DATABASE_URL at any other reachable Postgres
```

then set `DATABASE_URL` in `.env` (see `.env.example`):

```
DATABASE_URL=postgresql://localhost/apm_dev
```

Tables (`apm_processes`, `apm_events`, `apm_pending_actions`, plus the
checkpointer's own `checkpoint*` tables) are created automatically on
first use — no separate migration step. `DATABASE_URL` works just as
well pointed at a free managed Postgres (Neon, Supabase, etc.) for
quick testing with no local Postgres install at all — live-verified end
to end, including surviving a full container/task restart. One thing to
know if you do: a serverless provider like Neon auto-suspends its
compute after a few idle minutes, which used to surface as `SSL
connection has been closed unexpectedly` on the first call after a
while — both connection pools now pass `check=ConnectionPool.check_connection`,
so a connection killed while idle in the pool is detected and
transparently replaced rather than handed out broken
(`state/postgres_store.py`, `api/dependencies.py`).

`tests/test_postgres_state_store.py` and `tests/test_postgres_checkpointer.py`
exercise this against a real Postgres directly (not through the API
server); they're skipped automatically unless both the `postgres`
extra is installed and `APM_TEST_DATABASE_URL` points at a real,
reachable (and disposable — tests truncate its tables) database:

```
createdb apm_test
APM_TEST_DATABASE_URL=postgresql://localhost/apm_test pytest tests/test_postgres_state_store.py tests/test_postgres_checkpointer.py -q
```

## Run the API

```
uvicorn apm_connectors.api.app:app --reload --port 8000
```

Without `DATABASE_URL` set (above), this fails at startup with a clear
`RuntimeError` before the port even binds -- there is no file-backed/
in-memory fallback for the live server.

Sanity check it's up:

```
python scripts/api_smoke_test.py
```

No auth is needed for any of this by default — see
`docs/api-contract.md`'s "Auth is opt-in" for when to set
`APM_API_KEYS` (not something local dev needs).

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
set `APM_CONNECTORS_MCP_TRANSPORT=sse` or `streamable-http`. If the
`/tools/*` server it's pointed at has `APM_API_KEYS` configured, also
set `APM_CONNECTORS_API_KEY` to one of those keys so its calls
authenticate — unused, and safe to leave unset, against a server with
no auth configured.

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

See `docs/deployment.md` to run this same API as a container, either
locally with Docker or deployed to AWS ECS on Fargate.
