"""FastAPI dependency providers.

All cached (built once per running process, not per-request) since the
compiled graph's checkpointer holds paused/in-progress state (Postgres or
in memory, see get_action_graph below) for the lifetime of the server
process — a fresh graph per request would lose that state between a
write proposal and its decision for the same process_id.

Tests override these via `app.dependency_overrides` with a store/tools
built from fake clients (see tests/test_tools_api.py) — real credentials
are only needed to actually run the server, never to test it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from apm_connectors.config import load_settings
from apm_connectors.graph import build_action_graph
from apm_connectors.state.store import StateStore, StateStoreProtocol
from apm_connectors.tools.base import BaseTool
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
    default file-backed/in-memory setup never needs the optional
    `postgres` extra installed.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    settings = load_settings()
    assert settings.database_url is not None
    return ConnectionPool(
        settings.database_url,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        open=True,
    )


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
    resumes. With no `DATABASE_URL`, that's in memory (MemorySaver): a
    fine MVP default, but it means a restart loses anything mid-approval.
    With `DATABASE_URL` set, it's `PostgresSaver` instead, so a paused
    process survives a redeploy or a task replacement the same way the
    Postgres-backed StateStore does — the two settings are meant to be
    turned on together.
    """
    settings = load_settings()
    if settings.database_url:
        from langgraph.checkpoint.postgres import PostgresSaver

        checkpointer = PostgresSaver(_get_postgres_pool())
        checkpointer.setup()
    else:
        checkpointer = MemorySaver()
    return build_action_graph(get_tools(), get_state_store(), checkpointer=checkpointer)
