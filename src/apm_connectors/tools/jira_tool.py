"""Jira connector -- issue search/read and create/update.

Same shape as salesforce_tool.py: read (JQL search, read a single issue)
and write (create/update an issue) land together here. The
non-negotiable rule still applies in full: write methods default to
dry_run=True, log every call (including a real one) via
require_dry_run_guard, and are only ever safe to call with dry_run=False
from inside the action graph's execute_node (apm_connectors.graph), after
an approved human-approval interrupt -- see
.claude/skills/tool-integration/SKILL.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

from apm_connectors.config import Settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools._retry import with_retry
from apm_connectors.tools.base import ActionResult, BaseTool, Capability


class JiraClient(Protocol):
    """The minimal surface JiraTool needs from a Jira API client. Both
    the real client (`JiraRestClient`, below) and test fakes implement
    just this, so the connector's logic can be tested without live
    credentials.
    """

    def search_issues(self, jql: str, max_results: int) -> list[dict[str, Any]]: ...

    def get_issue(self, issue_key: str) -> dict[str, Any]: ...

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]: ...

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class JiraIssue:
    issue_key: str
    issue_type: str
    fields: dict[str, Any] = field(default_factory=dict)


class JiraTool(BaseTool):
    """Jira connector: JQL search / read an issue, and create/update an
    issue -- the latter only ever reachable through the action graph's
    approval interrupt (see apm_connectors.graph), same pattern as
    SalesforceTool.create_record/update_record.
    """

    name = "jira"
    capabilities = frozenset({Capability.READ, Capability.WRITE})

    def __init__(self, state: StateStore, client: JiraClient) -> None:
        super().__init__(state)
        self._client = client

    def health_check(self) -> bool:
        try:
            # Jira Cloud's search endpoint rejects an "unbounded" JQL query
            # (no restriction clause at all, even with just an ORDER BY) --
            # "assignee = currentUser()" is a restriction every account can
            # run with zero setup, valid whether or not it matches anything.
            self._client.search_issues("assignee = currentUser()", 1)
            return True
        except Exception:
            return False

    def search_issues(self, process_id: str, jql: str, max_results: int = 50) -> list[JiraIssue]:
        """Run a read-only JQL search (e.g.
        `"project = OPS AND status = 'In Progress' ORDER BY updated DESC"`)
        and return normalized issues. `max_results` caps the page size --
        this connector does not follow Jira's pagination beyond the
        first page.
        """
        raw_issues = self._client.search_issues(jql, max_results)
        issues = [self._to_issue(r) for r in raw_issues]
        self._log(
            process_id,
            "read",
            f"Searched Jira ('{jql}'), found {len(issues)} issue(s)",
            {"jql": jql, "count": len(issues)},
        )
        return issues

    def get_issue(self, process_id: str, issue_key: str) -> JiraIssue:
        issue = self._to_issue(self._client.get_issue(issue_key))
        self._log(
            process_id,
            "read",
            f"Read Jira issue {issue_key}",
            {"issue_key": issue_key},
        )
        return issue

    def create_issue(self, process_id: str, fields: dict[str, Any], dry_run: bool = True) -> ActionResult:
        """Create a new issue. `fields` is the Jira `fields` payload as-is
        (e.g. {"project": {"key": "OPS"}, "summary": "Fix the thing",
        "issuetype": {"name": "Bug"}}). Only ever call this with
        dry_run=False from inside the action graph, after the
        human-approval interrupt has returned an approval.
        """
        project_key = fields.get("project", {}).get("key", "?") if isinstance(fields.get("project"), dict) else "?"
        summary = f"Create Jira issue in project {project_key}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(executed=False, description=summary, details={"fields": fields})

        created = self._client.create_issue(fields)
        return ActionResult(
            executed=True,
            description=summary,
            details={"fields": fields, "issue_key": created.get("key")},
        )

    def update_issue(
        self, process_id: str, issue_key: str, fields: dict[str, Any], dry_run: bool = True
    ) -> ActionResult:
        """Update an existing issue's fields (e.g. issue_key="OPS-42",
        fields={"summary": "Updated title"}). Only ever call this with
        dry_run=False from inside the action graph, after the
        human-approval interrupt has returned an approval.
        """
        summary = f"Update Jira issue {issue_key}"
        self.require_dry_run_guard(dry_run, process_id, summary)

        if dry_run:
            return ActionResult(
                executed=False,
                description=summary,
                details={"issue_key": issue_key, "fields": fields},
            )

        self._client.update_issue(issue_key, fields)
        return ActionResult(
            executed=True,
            description=summary,
            details={"issue_key": issue_key, "fields": fields},
        )

    @staticmethod
    def _to_issue(raw: dict[str, Any]) -> JiraIssue:
        raw_fields = raw.get("fields", {}) if isinstance(raw.get("fields"), dict) else {}
        issuetype = raw_fields.get("issuetype", {})
        issue_type = issuetype.get("name", "") if isinstance(issuetype, dict) else ""
        return JiraIssue(issue_key=raw.get("key", ""), issue_type=issue_type, fields=raw_fields)


class JiraRestClient:
    """Real Jira Cloud REST API client, authenticating with an
    Atlassian API token (Basic auth: account email + token) --
    apm_connectors.tools.jira_tool.build_configured_jira_tool builds one
    directly from Settings, with no separate token-exchange step (unlike
    salesforce_auth.py's OAuth flow): Jira Cloud's API-token Basic auth
    needs no network round trip to mint a credential, just the header.

    Uses /rest/api/3/search/jql (POST) rather than the older
    /rest/api/3/search (GET) for search_issues -- Atlassian deprecated
    the GET endpoint in favor of this one for Jira Cloud. Two live-
    verified quirks of that newer endpoint, both handled here: (1) it
    rejects an "unbounded" JQL query with no restriction clause at all
    (JiraTool.health_check works around this by querying `assignee =
    currentUser()` rather than a bare ORDER BY); (2) unlike a plain GET
    /issue/{key}, it returns bare {"id": ...} entries with no "key" or
    "fields" unless a "fields" param is passed explicitly (search_issues
    always passes ["*all"] to match get_issue's default).
    """

    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self._base = f"{base_url.rstrip('/')}/rest/api/3"
        self._auth = (email, api_token)

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json"}

    @with_retry()
    def search_issues(self, jql: str, max_results: int) -> list[dict[str, Any]]:
        import requests

        response = requests.post(
            f"{self._base}/search/jql",
            auth=self._auth,
            headers=self._headers(),
            # "fields": ["*all"] matches get_issue's default (a plain GET
            # /issue/{key} returns every field) -- without it, /search/jql
            # returns bare {"id": ...} entries with no "key" or "fields"
            # at all, unlike the old, now-deprecated /search endpoint.
            json={"jql": jql, "maxResults": max_results, "fields": ["*all"]},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("issues", [])

    @with_retry()
    def get_issue(self, issue_key: str) -> dict[str, Any]:
        import requests

        response = requests.get(
            f"{self._base}/issue/{quote(issue_key)}",
            auth=self._auth,
            headers=self._headers(),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    # Deliberately NOT retried -- see apm_connectors.tools._retry's module
    # docstring: a dropped connection after Jira already created the
    # issue must not turn into an automatic duplicate.
    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        import requests

        response = requests.post(
            f"{self._base}/issue",
            auth=self._auth,
            headers=self._headers(),
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    # Deliberately NOT retried, same reasoning as create_issue.
    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        import requests

        response = requests.put(
            f"{self._base}/issue/{quote(issue_key)}",
            auth=self._auth,
            headers=self._headers(),
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        return {"key": issue_key} if response.status_code == 204 else response.json()


def build_configured_jira_tool(state: StateStore, settings: Settings) -> JiraTool | None:
    """Build the JiraTool this server is configured for, same "None when
    unconfigured" spirit as salesforce_tool.build_configured_salesforce_tool
    -- api.dependencies.get_tools() simply omits "jira" from its dict
    when this returns None, and every /tools/jira/* route then 503s
    individually rather than the whole API failing to start.

    Requires JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN -- see .env.example.
    """
    if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
        return None

    return JiraTool(state, JiraRestClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token))
