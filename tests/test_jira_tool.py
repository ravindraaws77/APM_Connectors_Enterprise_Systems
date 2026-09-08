from pathlib import Path
from typing import Any

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.base import Capability
from apm_connectors.tools.jira_tool import JiraTool, build_configured_jira_tool


class FakeJiraClient:
    """Implements the JiraClient protocol in-memory — no network, no
    credentials — so JiraTool's logic can be unit tested directly.
    """

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self._issues = {i["key"]: i for i in issues}
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []

    def search_issues(self, jql: str, max_results: int) -> list[dict[str, Any]]:
        return list(self._issues.values())[:max_results]

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        return self._issues[issue_key]

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        self.created.append({"fields": fields})
        return {"key": f"OPS-{len(self.created)}"}

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.updated.append({"issue_key": issue_key, "fields": fields})
        return {"key": issue_key}


class BrokenJiraClient:
    def search_issues(self, jql: str, max_results: int) -> list[dict[str, Any]]:
        raise RuntimeError("simulated API failure")

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated API failure")


def _raw_issue(issue_key: str, issue_type: str, **fields: Any) -> dict[str, Any]:
    return {"key": issue_key, "fields": {"issuetype": {"name": issue_type}, **fields}}


def _settings(
    *,
    jira_base_url: str | None = None,
    jira_email: str | None = None,
    jira_api_token: str | None = None,
) -> Settings:
    return Settings(
        google_client_id=None,
        google_client_secret=None,
        excel_workbook_path=None,
        excel_drive_file_id=None,
        state_dir=Path("state"),
        jira_base_url=jira_base_url,
        jira_email=jira_email,
        jira_api_token=jira_api_token,
    )


def test_jira_tool_capabilities() -> None:
    assert JiraTool.capabilities == frozenset({Capability.READ, Capability.WRITE})


def test_search_issues_returns_normalized_issues_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([_raw_issue("OPS-1", "Bug", summary="Payments failing")])
    tool = JiraTool(store, client)

    jql = "project = OPS AND status = 'In Progress'"
    results = tool.search_issues("order-123", jql)

    assert len(results) == 1
    assert results[0].issue_key == "OPS-1"
    assert results[0].issue_type == "Bug"
    assert results[0].fields["summary"] == "Payments failing"

    events = store.list_events("order-123")
    assert any(e["event_type"] == "read" and e["details"]["jql"] == jql for e in events)


def test_get_issue(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([_raw_issue("OPS-2", "Task", summary="Renew license")])
    tool = JiraTool(store, client)

    issue = tool.get_issue("order-1", "OPS-2")

    assert issue.issue_key == "OPS-2"
    assert issue.issue_type == "Task"
    assert issue.fields["summary"] == "Renew license"

    events = store.list_events("order-1")
    assert any(e["event_type"] == "read" and e["details"]["issue_key"] == "OPS-2" for e in events)


def test_health_check_true(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = JiraTool(store, FakeJiraClient([]))
    assert tool.health_check() is True


def test_health_check_false_on_client_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    tool = JiraTool(store, BrokenJiraClient())
    assert tool.health_check() is False


def test_create_issue_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([])
    tool = JiraTool(store, client)

    fields = {"project": {"key": "OPS"}, "summary": "Fix the thing", "issuetype": {"name": "Bug"}}
    result = tool.create_issue("order-1", fields)

    assert result.executed is False
    assert client.created == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_create_issue_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([])
    tool = JiraTool(store, client)

    fields = {"project": {"key": "OPS"}, "summary": "Fix the thing", "issuetype": {"name": "Bug"}}
    result = tool.create_issue("order-1", fields, dry_run=False)

    assert result.executed is True
    assert result.details["issue_key"] == "OPS-1"
    assert client.created == [{"fields": fields}]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)


def test_update_issue_dry_run_does_not_call_client(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([])
    tool = JiraTool(store, client)

    result = tool.update_issue("order-1", "OPS-1", {"summary": "Updated title"})

    assert result.executed is False
    assert client.updated == []
    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_proposed" and e["details"]["dry_run"] is True for e in events)


def test_update_issue_real_call_invokes_client_and_logs(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    client = FakeJiraClient([])
    tool = JiraTool(store, client)

    result = tool.update_issue("order-1", "OPS-1", {"summary": "Updated title"}, dry_run=False)

    assert result.executed is True
    assert client.updated == [{"issue_key": "OPS-1", "fields": {"summary": "Updated title"}}]

    events = store.list_events("order-1")
    assert any(e["event_type"] == "action_executed" and e["details"]["dry_run"] is False for e in events)


def test_build_configured_jira_tool_returns_none_when_unconfigured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_jira_tool(store, _settings())

    assert result is None


def test_build_configured_jira_tool_returns_none_when_partially_configured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_jira_tool(
        store, _settings(jira_base_url="https://acme.atlassian.net", jira_email="bot@acme.com")
    )

    assert result is None


def test_build_configured_jira_tool_builds_when_fully_configured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    settings = _settings(
        jira_base_url="https://acme.atlassian.net", jira_email="bot@acme.com", jira_api_token="token123"
    )

    tool = build_configured_jira_tool(store, settings)

    assert isinstance(tool, JiraTool)
