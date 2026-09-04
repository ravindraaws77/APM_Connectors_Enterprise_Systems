"""A small, dependency-free, file-backed store for process status and the
audit log. This is the "Memory & Persistence" cross-cutting layer for the
MVP: everything the agent does gets written here so status survives a
restart and is available to the UI (phase 6) and to whoever needs to
answer "what happened and why".

Swap-out note: this is intentionally simple (a JSON file + a lock) so the
MVP has zero extra infra to run. `docs/roadmap.md` calls out swapping this
for Postgres as a later, non-MVP phase — callers should only use the
methods below (not the file format) so that swap doesn't ripple outward.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

EventType = Literal[
    "read",
    "action_proposed",
    "action_approved",
    "action_rejected",
    "action_executed",
    "action_failed",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AuditEvent:
    id: str
    timestamp: str
    process_id: str
    tool: str
    event_type: EventType
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class StateStore:
    """Thread-safe, file-backed status + audit store.

    One JSON file holds everything for the MVP's scale (a handful of
    processes, a modest audit trail) — see the module docstring for the
    swap-out plan once that stops being true.
    """

    def __init__(self, path: Path | str = Path("state") / "apm_state.json") -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({"processes": {}, "events": []})

    # -- internal helpers ---------------------------------------------

    def _read(self) -> dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict[str, Any]) -> None:
        tmp_path = self._path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        tmp_path.replace(self._path)

    # -- process status --------------------------------------------------

    def get_status(self, process_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read()["processes"].get(process_id)

    def set_status(self, process_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            process = data["processes"].setdefault(
                process_id, {"process_id": process_id, "created_at": _now()}
            )
            process.update(fields)
            process["updated_at"] = _now()
            self._write(data)
            return process

    def list_processes(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read()["processes"].values())

    # -- audit log ------------------------------------------------------

    def log_event(
        self,
        process_id: str,
        tool: str,
        event_type: EventType,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            id=str(uuid.uuid4()),
            timestamp=_now(),
            process_id=process_id,
            tool=tool,
            event_type=event_type,
            summary=summary,
            details=details or {},
        )
        with self._lock:
            data = self._read()
            data["events"].append(asdict(event))
            self._write(data)
        return event

    def list_events(
        self, process_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = self._read()["events"]
        if process_id is not None:
            events = [e for e in events if e["process_id"] == process_id]
        if limit is not None:
            events = events[-limit:]
        return events

    # -- pending approvals ------------------------------------------------
    # A "pending action" is a write/action the agent has proposed but that
    # has not yet been approved or rejected by a human. The UI (phase 6)
    # reads this list to render Approve/Reject buttons; the agent (phase 5)
    # writes to it via `interrupt()` and reads the resolution back.

    def add_pending_action(
        self,
        process_id: str,
        tool: str,
        description: str,
        payload: dict[str, Any],
        category: str = "other",
    ) -> dict[str, Any]:
        """`category` is a short, stable slug (e.g. "shipment_delay") from
        the reasoner's classification of the underlying situation — see
        apm_connectors.agent.reasoner.SYSTEM_PROMPT. Carried on the action record and
        included in every audit event logged for it, so the UI's History
        table can color-code by category to surface recurring patterns
        across processes, not just within one.
        """
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
        with self._lock:
            data = self._read()
            data.setdefault("pending_actions", []).append(action)
            self._write(data)
        self.log_event(process_id, tool, "action_proposed", description, {"category": category, **payload})
        return action

    def list_pending_actions(self, process_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            actions = self._read().get("pending_actions", [])
        actions = [a for a in actions if a["status"] == "pending"]
        if process_id is not None:
            actions = [a for a in actions if a["process_id"] == process_id]
        return actions

    def resolve_pending_action(
        self, action_id: str, approved: bool
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            actions = data.get("pending_actions", [])
            action = next((a for a in actions if a["id"] == action_id), None)
            if action is None:
                return None
            action["status"] = "approved" if approved else "rejected"
            action["resolved_at"] = _now()
            self._write(data)
        self.log_event(
            action["process_id"],
            action["tool"],
            "action_approved" if approved else "action_rejected",
            action["description"],
            {"category": action.get("category", "other"), **action["payload"]},
        )
        return action
