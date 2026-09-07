"""Fixtures for full-stack integration tests: a real `uvicorn` server
bound to a real socket, driven over real HTTP -- unlike
tests/test_tools_api.py's `TestClient` (in-process ASGI calls), this is
what an actual deployed reasoning/orchestration layer, or
scripts/api_smoke_test.py, talks to.

Still uses the same fake connector clients as the rest of the suite
(tests/test_gmail_tool.py, tests/test_calendar_tool.py,
tests/test_excel_file_tool.py) -- no live credentials, no real network
call to Gmail/Calendar/Excel, and no dependency on anything actually
being deployed.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import pytest
import requests
import uvicorn
from langgraph.checkpoint.memory import MemorySaver

from apm_connectors.api.app import create_app
from apm_connectors.api.dependencies import get_action_graph, get_state_store, get_tools
from apm_connectors.graph import build_action_graph
from apm_connectors.state.store import StateStore
from apm_connectors.tools.calendar_tool import CalendarTool
from apm_connectors.tools.excel_file_tool import ExcelFileTool
from apm_connectors.tools.gmail_tool import GmailTool
from tests.test_calendar_tool import FakeCalendarClient
from tests.test_excel_file_tool import FakeWorkbookSource, _sample_workbook_bytes
from tests.test_gmail_tool import FakeGmailClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class LiveServer:
    base_url: str
    store: StateStore
    gmail_client: FakeGmailClient
    calendar_client: FakeCalendarClient
    excel_source: FakeWorkbookSource | None


def _start(server: uvicorn.Server, base_url: str) -> threading.Thread:
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                return thread
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError(f"integration test server at {base_url} did not become healthy in time")


@pytest.fixture()
def live_server_factory(tmp_path: Path) -> Iterator[Callable[..., LiveServer]]:
    """Factory so a test can opt out of a connector (e.g. to exercise
    the "unconfigured tool" 503 path) the same way
    tests/test_tools_api.py's `_client(..., with_excel=False)` does.
    """
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def _make(with_excel: bool = True) -> LiveServer:
        store = StateStore(tmp_path / f"state-{len(servers)}.json")
        gmail_client = FakeGmailClient([])
        calendar_client = FakeCalendarClient([])
        tools = {
            "gmail": GmailTool(store, gmail_client),
            "google_calendar": CalendarTool(store, calendar_client),
        }
        excel_source: FakeWorkbookSource | None = None
        if with_excel:
            excel_source = FakeWorkbookSource(_sample_workbook_bytes())
            tools["excel_file"] = ExcelFileTool(store, excel_source)

        action_graph = build_action_graph(tools, store, checkpointer=MemorySaver())

        app = create_app()
        app.dependency_overrides[get_state_store] = lambda: store
        app.dependency_overrides[get_tools] = lambda: tools
        app.dependency_overrides[get_action_graph] = lambda: action_graph

        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = _start(server, base_url)
        servers.append((server, thread))

        return LiveServer(base_url, store, gmail_client, calendar_client, excel_source)

    yield _make

    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture()
def live_server(live_server_factory: Callable[..., LiveServer]) -> LiveServer:
    return live_server_factory()
