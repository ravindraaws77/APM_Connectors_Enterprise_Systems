"""FastAPI dependency providers.

All cached (built once per running process, not per-request) since the
compiled graph's checkpointer holds paused/in-progress state (Postgres or
SQLite, see get_action_graph below) for the lifetime of the server
process — a fresh graph per request would lose that state between a
write proposal and its decision for the same process_id.

Tests override these via `app.dependency_overrides` with a store/tools
built from fake clients (see tests/test_tools_api.py) — real credentials
are only needed to actually run the server, never to test it.

require_caller (the auth dependency, at the bottom) is the one exception
to "built once": it runs on every request, since it has to look at that
request's own Authorization header.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.sqlite import SqliteSaver

from apm_connectors.config import load_settings
from apm_connectors.graph import build_action_graph
from apm_connectors.state.store import StateStore, StateStoreProtocol
from apm_connectors.tools.base import BaseTool
from apm_connectors.tools.drive_tool import build_configured_drive_tool
from apm_connectors.tools.excel_file_tool import build_configured_excel_tool
from apm_connectors.tools.google_auth import build_gmail_and_calendar_tools
from apm_connectors.tools.jira_tool import build_configured_jira_tool
from apm_connectors.tools.salesforce_tool import build_configured_salesforce_tool


@lru_cache
def _get_postgres_pool() -> Any:
    """One connection pool, shared by the Postgres state store and the
    Postgres checkpointer below, so a Postgres-backed deployment opens
    one pool of connections to the database rather than two. Only ever
    called when `DATABASE_URL` is set -- imports psycopg lazily so the
    default file-backed/SQLite-backed setup never needs the optional
    `postgres` extra installed.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    settings = load_settings()
    assert settings.database_url is not None
    return ConnectionPool(
        settings.database_url,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        # check=check_connection: verify a connection is actually alive
        # before handing it out, replacing it transparently if not --
        # see the identical comment in state/postgres_store.py, which
        # this pool is shared with. Without this, a serverless Postgres
        # (Neon, etc.) suspending its compute while a pooled connection
        # sits idle breaks every call using it, indefinitely, with "SSL
        # connection has been closed unexpectedly" -- live-verified.
        check=ConnectionPool.check_connection,
        open=True,
    )


@lru_cache
def _get_sqlite_connection() -> Any:
    """One sqlite3 connection for the default (no DATABASE_URL) SQLite
    checkpointer below, opened once per process next to the file-backed
    StateStore's own JSON file (same `APM_STATE_DIR`). Only ever called
    when `database_url` is unset.

    check_same_thread=False because this connection is shared across
    requests, and FastAPI's sync `def` route handlers (every /tools/*
    write route) run in a threadpool, not all on one thread; SqliteSaver
    serializes access to a shared connection internally with its own
    lock, so a single connection here is safe to reuse concurrently.
    """
    settings = load_settings()
    settings.state_dir.mkdir(parents=True, exist_ok=True)

    import sqlite3

    return sqlite3.connect(str(settings.state_dir / "checkpoints.sqlite"), check_same_thread=False)


@lru_cache
def get_state_store() -> StateStoreProtocol:
    settings = load_settings()
    if settings.database_url:
        from apm_connectors.state.postgres_store import PostgresStateStore

        return PostgresStateStore(_get_postgres_pool())
    return StateStore()


@lru_cache
def get_tools() -> dict[str, BaseTool]:
    """The connector layer's tool instances, shared by the action graph
    and the /tools/* read routes — one set of connectors, built once.

    Each connector is independently optional: a deployment configures
    whichever ones it has credentials for, and /tools/* routes for an
    unconfigured tool 503 individually (apm_connectors.api.tools_routes'
    `_tool` helper) rather than the whole API failing to start or every
    route breaking because one connector's credentials are missing.
    Gmail/Calendar share one Google OAuth consent (both scopes in one
    token), so they're built together and both omitted together if that
    fails.
    """
    settings = load_settings()
    state = get_state_store()
    tools: dict[str, BaseTool] = {}

    try:
        gmail_tool, calendar_tool = build_gmail_and_calendar_tools(state, settings)
    except RuntimeError:
        pass
    else:
        tools["gmail"] = gmail_tool
        tools["google_calendar"] = calendar_tool

    excel_tool = build_configured_excel_tool(state, settings)
    if excel_tool is not None:
        tools["excel_file"] = excel_tool

    drive_tool = build_configured_drive_tool(state, settings)
    if drive_tool is not None:
        tools["drive"] = drive_tool

    salesforce_tool = build_configured_salesforce_tool(state, settings)
    if salesforce_tool is not None:
        tools["salesforce"] = salesforce_tool

    jira_tool = build_configured_jira_tool(state, settings)
    if jira_tool is not None:
        tools["jira"] = jira_tool

    return tools


@lru_cache
def get_action_graph():
    """The propose -> approval -> execute graph every /tools/* write
    route drives. See apm_connectors.graph.build_action_graph.

    The checkpointer holds every paused (proposed-but-not-yet-decided)
    process's graph state — this is what a human approval decision
    resumes. With no `DATABASE_URL`, that's a local SQLite file next to
    the file-backed StateStore's own JSON file (`SqliteSaver`, see
    `_get_sqlite_connection` above): a restart or crash no longer loses
    anything mid-approval, at the same zero-infra cost as the file-backed
    StateStore default. With `DATABASE_URL` set, it's `PostgresSaver`
    instead, so a paused process also survives losing the local disk
    entirely — a redeploy or an ECS task replacement — the same way the
    Postgres-backed StateStore does — the two settings are meant to be
    turned on together.
    """
    settings = load_settings()
    if settings.database_url:
        from langgraph.checkpoint.postgres import PostgresSaver

        checkpointer = PostgresSaver(_get_postgres_pool())
        checkpointer.setup()
    else:
        checkpointer = SqliteSaver(_get_sqlite_connection())
        checkpointer.setup()
    return build_action_graph(get_tools(), get_state_store(), checkpointer=checkpointer)


@lru_cache
def get_api_keys() -> dict[str, str]:
    """{key: caller_name}, parsed once per process from APM_API_KEYS.
    Empty means auth is off -- see require_caller below.
    """
    return load_settings().api_keys


_bearer_scheme = HTTPBearer(auto_error=False)


def require_caller(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> str | None:
    """The auth gate for every /tools/* and /processes/* route (never
    /health -- a load balancer's health check carries no credentials).

    Opt-in, like every other piece of optional config in this package
    (Excel/Salesforce/Jira/Drive: unset env var = feature absent): with
    no APM_API_KEYS configured, this returns None and every route
    behaves exactly as documented today ("No auth today" in
    docs/api-contract.md) -- the local-dev default. Once APM_API_KEYS
    is set, every request needs `Authorization: Bearer <key>` matching
    one of the configured keys, or this raises 401.

    The return value -- the caller's configured name, or None when auth
    is off -- is what a write-proposing or decision route passes through
    to the state store as `proposed_by`/`decided_by` (see graph.py and
    state/store.py), so the audit trail can say *who*, not just *what*,
    once this is turned on. A route that doesn't need that value still
    gets the same 401 gate via the router-level dependency
    (tools_routes.router's `dependencies=`) without declaring this
    parameter itself.
    """
    api_keys = get_api_keys()
    if not api_keys:
        return None
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    caller = api_keys.get(credentials.credentials)
    if caller is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return caller
