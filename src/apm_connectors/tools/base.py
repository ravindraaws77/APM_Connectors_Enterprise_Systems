"""Common interface every tool connector (Gmail, Calendar, Excel, ...)
implements, so the agent graph and the UI can treat them uniformly.

See .claude/skills/tool-integration/SKILL.md for the rules a new connector
must follow (read-before-write, dry_run, audit logging, capability-map
entry). This module only defines the shared shape — no connector logic
lives here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from apm_connectors.state.store import StateStore


class Capability(str, Enum):
    READ = "read"
    WRITE = "write"
    ACTION = "action"


@dataclass(frozen=True)
class ActionResult:
    """What a write/action call returns, whether it actually ran or was
    a dry run — callers (the agent, tests, the UI) treat both the same
    shape, checking `executed` to tell them apart.
    """

    executed: bool
    description: str
    details: dict[str, Any]


class BaseTool(ABC):
    """Base class for a connector to one external system.

    Subclasses must set `name` and `capabilities`, and must route every
    public read/write/action method through `self._log(...)` so nothing
    happens off the audit trail.
    """

    name: str
    capabilities: frozenset[Capability]

    def __init__(self, state: StateStore) -> None:
        self._state = state

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def _log(
        self,
        process_id: str,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._state.log_event(
            process_id=process_id,
            tool=self.name,
            event_type=event_type,  # type: ignore[arg-type]
            summary=summary,
            details=details or {},
        )

    @abstractmethod
    def health_check(self) -> bool:
        """Cheap call to confirm credentials/config are usable. Must not
        require any write/action scope, and must never raise — return
        False on failure so the UI can show connection status.
        """

    def require_dry_run_guard(self, dry_run: bool, process_id: str, summary: str) -> None:
        """Call at the top of every write/action method as a defense in
        depth alongside the agent-level interrupt() gate (phase 5). This
        does not replace the human-approval interrupt — it just makes it
        impossible for a connector to silently skip the audit trail on a
        real (non-dry-run) call.

        Logs "action_executed" for a real call, or "action_proposed" for a
        dry run (a preview of what would happen, not a read).
        """
        event_type = "action_executed" if not dry_run else "action_proposed"
        self._log(process_id, event_type, summary, {"dry_run": dry_run})
