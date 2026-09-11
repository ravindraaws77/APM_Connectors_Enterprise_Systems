"""Postgres-backed implementation of the same status + audit log
interface as `apm_connectors.state.store.StateStore` (get_status,
set_status, list_processes, log_event, list_events, add_pending_action,
list_pending_actions, resolve_pending_action) — see that module's
docstring for why callers only ever depend on this method surface, never
on which implementation is behind it.

Swap this in (instead of the file-backed default) by setting
`DATABASE_URL`; `apm_connectors.api.dependencies.get_state_store` picks
between the two based on that alone. Requires the optional `postgres`
extra (`pip install -e ".[postgres]"`) -- imported lazily by
dependencies.py so the zero-infra file-backed default never needs
psycopg installed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from apm_connectors.state.store import EventType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS apm_processes (
    process_id TEXT PRIMARY KEY,
    fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS apm_events (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS apm_events_process_id_idx ON apm_events (process_id, created_at);

CREATE TABLE IF NOT EXISTS apm_pending_actions (
    id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    description TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    category TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS apm_pending_actions_status_idx ON apm_pending_actions (status, process_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class PostgresStateStore:
    """Same contract as StateStore, backed by Postgres instead of a JSON
    file, so status/audit/pending-approval state survives a redeploy or
    a task replacement (see docs/deployment.md's "State is ephemeral"
    known limitation) and is safe for more than one API process to share.

    A connection pool may be passed in directly to share one pool with
    the Postgres checkpointer (see api/dependencies.py) rather than
    opening a second set of connections to the same database.
    """

    def __init__(self, dsn_or_pool: str | ConnectionPool) -> None:
        if isinstance(dsn_or_pool, ConnectionPool):
            self._pool = dsn_or_pool
            self._owns_pool = False
        else:
            # autocommit (each call is its own statement, same
            # write-immediately shape as the file store) and
            # prepare_threshold=None (never use server-side prepared
            # statements), so this also behaves correctly if DATABASE_URL
            # points at a transaction-mode connection pooler such as
            # pgbouncer/RDS Proxy, which prepared statements break.
            self._pool = ConnectionPool(
                dsn_or_pool,
                kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                open=True,
            )
            self._owns_pool = True
        self._setup()

    def close(self) -> None:
        if self._owns_pool:
            self._pool.close()

    def _setup(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(_SCHEMA)

    def _connection(self):
        return self._pool.connection()

    # -- process status --------------------------------------------------

    def get_status(self, process_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT process_id, fields, created_at, updated_at "
                "FROM apm_processes WHERE process_id = %s",
                (process_id,),
            ).fetchone()
        return _process_row_to_dict(row) if row is not None else None

    def set_status(self, process_id: str, **fields: Any) -> dict[str, Any]:
        now = _now()
        with self._connection() as conn:
            row = conn.execute(
                """
                INSERT INTO apm_processes (process_id, fields, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (process_id) DO UPDATE
                SET fields = apm_processes.fields || EXCLUDED.fields,
                    updated_at = EXCLUDED.updated_at
                RETURNING process_id, fields, created_at, updated_at
                """,
                (process_id, Jsonb(fields), now, now),
            ).fetchone()
        return _process_row_to_dict(row)

    def list_processes(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT process_id, fields, created_at, updated_at "
                "FROM apm_processes ORDER BY created_at",
            ).fetchall()
        return [_process_row_to_dict(row) for row in rows]

    # -- audit log ------------------------------------------------------

    def log_event(
        self,
        process_id: str,
        tool: str,
        event_type: EventType,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "timestamp": _now(),
            "process_id": process_id,
            "tool": tool,
            "event_type": event_type,
            "summary": summary,
            "details": details or {},
        }
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO apm_events (id, process_id, tool, event_type, summary, details, created_at)
                VALUES (%(id)s, %(process_id)s, %(tool)s, %(event_type)s, %(summary)s, %(details)s, %(timestamp)s)
                """,
                {**event, "details": Jsonb(event["details"])},
            )
        return {**event, "timestamp": _iso(event["timestamp"])}

    def list_events(
        self, process_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT id, process_id, tool, event_type, summary, details, created_at FROM apm_events"
        params: list[Any] = []
        if process_id is not None:
            query += " WHERE process_id = %s"
            params.append(process_id)
        query += " ORDER BY created_at"
        if limit is not None:
            query += " DESC LIMIT %s"
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(query, params or None).fetchall()
        events = [_event_row_to_dict(row) for row in rows]
        if limit is not None:
            events.reverse()
        return events

    # -- pending approvals ------------------------------------------------

    def add_pending_action(
        self,
        process_id: str,
        tool: str,
        description: str,
        payload: dict[str, Any],
        category: str = "other",
    ) -> dict[str, Any]:
        action = {
            "id": str(uuid.uuid4()),
            "process_id": process_id,
            "tool": tool,
            "description": description,
            "payload": payload,
            "category": category,
            "status": "pending",
            "created_at": _now(),
        }
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO apm_pending_actions
                    (id, process_id, tool, description, payload, category, status, created_at)
                VALUES
                    (%(id)s, %(process_id)s, %(tool)s, %(description)s, %(payload)s,
                     %(category)s, %(status)s, %(created_at)s)
                """,
                {**action, "payload": Jsonb(action["payload"])},
            )
        self.log_event(process_id, tool, "action_proposed", description, {"category": category, **payload})
        return {**action, "created_at": _iso(action["created_at"])}

    def list_pending_actions(self, process_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT id, process_id, tool, description, payload, category, status, created_at, resolved_at "
            "FROM apm_pending_actions WHERE status = 'pending'"
        )
        params: list[Any] = []
        if process_id is not None:
            query += " AND process_id = %s"
            params.append(process_id)
        query += " ORDER BY created_at"
        with self._connection() as conn:
            rows = conn.execute(query, params or None).fetchall()
        return [_pending_action_row_to_dict(row) for row in rows]

    def resolve_pending_action(self, action_id: str, approved: bool) -> dict[str, Any] | None:
        status = "approved" if approved else "rejected"
        now = _now()
        with self._connection() as conn:
            row = conn.execute(
                """
                UPDATE apm_pending_actions
                SET status = %s, resolved_at = %s
                WHERE id = %s AND status = 'pending'
                RETURNING id, process_id, tool, description, payload, category, status, created_at, resolved_at
                """,
                (status, now, action_id),
            ).fetchone()
        if row is None:
            return None
        action = _pending_action_row_to_dict(row)
        self.log_event(
            action["process_id"],
            action["tool"],
            "action_approved" if approved else "action_rejected",
            action["description"],
            {"category": action.get("category", "other"), **action["payload"]},
        )
        return action


def _process_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "process_id": row["process_id"],
        **row["fields"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _event_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "timestamp": _iso(row["created_at"]),
        "process_id": row["process_id"],
        "tool": row["tool"],
        "event_type": row["event_type"],
        "summary": row["summary"],
        "details": row["details"],
    }


def _pending_action_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    action = {
        "id": row["id"],
        "process_id": row["process_id"],
        "tool": row["tool"],
        "description": row["description"],
        "payload": row["payload"],
        "category": row["category"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
    }
    if row["resolved_at"] is not None:
        action["resolved_at"] = _iso(row["resolved_at"])
    return action
