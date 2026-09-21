"""GET /metrics -- a Prometheus text-exposition-format snapshot of the
numbers cheap to compute at scrape time from the state store and each
configured connector's own health_check(): pending actions (overall and
per tool), connector health, and total processes ever recorded.

Deliberately NOT the full metrics story the observability doc's roadmap
describes: approval latency, rejection rate, and per-tool error rate
each need a real counter incremented at the point the event happens
(tools/base.py's _log/record_failure, graph.py's resolve_pending_action)
or an aggregation query over the full event history -- neither exists
yet, and list_events() has no way to filter/aggregate by event_type
short of scanning everything, which doesn't belong on every scrape.
This is the honest, cheap-today subset; see that doc for the rest.

Hand-rolled rather than a `prometheus_client` dependency -- three gauges
don't need a metrics library, and this repo already prefers a small
dependency-free module over a new one where the two are equivalent
(see logging_config.py, state/store.py's own module docstring).
"""

from __future__ import annotations

from apm_connectors.state.store import StateStoreProtocol
from apm_connectors.tools.base import BaseTool


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_metrics(store: StateStoreProtocol, tools: dict[str, BaseTool]) -> str:
    lines: list[str] = []

    pending = store.list_pending_actions()
    lines += [
        "# HELP apm_pending_actions_total Actions currently awaiting a human decision.",
        "# TYPE apm_pending_actions_total gauge",
        f"apm_pending_actions_total {len(pending)}",
    ]

    per_tool: dict[str, int] = {}
    for action in pending:
        per_tool[action["tool"]] = per_tool.get(action["tool"], 0) + 1
    lines += [
        "# HELP apm_pending_actions_by_tool Actions currently awaiting a human decision, by tool.",
        "# TYPE apm_pending_actions_by_tool gauge",
    ]
    for tool_name, count in sorted(per_tool.items()):
        lines.append(f'apm_pending_actions_by_tool{{tool="{_escape_label(tool_name)}"}} {count}')

    lines += [
        "# HELP apm_connector_healthy Whether a configured connector's health_check() currently passes.",
        "# TYPE apm_connector_healthy gauge",
    ]
    for tool_name, tool in sorted(tools.items()):
        healthy = 1 if tool.health_check() else 0
        lines.append(f'apm_connector_healthy{{tool="{_escape_label(tool_name)}"}} {healthy}')

    lines += [
        "# HELP apm_processes_total Every process this server's state store has ever recorded.",
        "# TYPE apm_processes_total gauge",
        f"apm_processes_total {len(store.list_processes())}",
    ]

    return "\n".join(lines) + "\n"
