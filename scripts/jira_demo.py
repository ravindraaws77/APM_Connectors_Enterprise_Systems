"""Manual smoke-test for the Jira connector -- run this yourself once you
have a real Atlassian API token; it is not part of the automated test
suite (that uses a fake client, see tests/test_jira_tool.py).

Setup (one-time):
  1. Create (or get access to) a Jira Cloud site, e.g.
     https://yourcompany.atlassian.net, and at least one project in it.
  2. Create an API token at
     https://id.atlassian.com/manage-profile/security/api-tokens.
  3. Copy .env.example to .env and fill in JIRA_BASE_URL / JIRA_EMAIL /
     JIRA_API_TOKEN.
  4. pip install -e ".[connectors]"

Usage:
  # Health check + a default JQL search (your 5 most recently created issues):
  python scripts/jira_demo.py

  # A JQL search of your choice:
  python scripts/jira_demo.py --search "project = OPS AND status = 'In Progress'"

  # Read a single issue by key:
  python scripts/jira_demo.py --read OPS-1

  # Exercise create/update -- ALWAYS dry_run here (this script never sets
  # dry_run=False; a real write is only ever safe from inside the action
  # graph's execute_node after a human-approval interrupt, see
  # .claude/skills/tool-integration/SKILL.md). This just proves the call
  # shape and logging work against a real Jira site.
  python scripts/jira_demo.py --create OPS "Fix the thing" Task
  python scripts/jira_demo.py --update OPS-1 summary="Updated title"

To exercise a *real* write (dry_run=False), go through the approval-gated
API instead of this script -- start the server
(`uvicorn apm_connectors.api.app:app --port 8000`), POST the write to
`/tools/jira/create` or `/tools/jira/update`, then POST
`{"approved": true}` to `/tools/actions/{action_id}/decision` (use the
top-level `action_id` from the propose response, not the one nested
inside `pending_action`) -- see docs/api-contract.md.

This only ever performs read calls against the site, plus dry-run (no-op)
create/update calls -- nothing is written to Jira.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.jira_tool import build_configured_jira_tool

DEFAULT_JQL = "ORDER BY created DESC"
DEFAULT_MAX_RESULTS = 5


def _parse_fields(pairs: list[str]) -> dict[str, str]:
    fields = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        fields[key] = value
    return fields


def main() -> None:
    args = sys.argv[1:]
    settings = load_settings()
    store = StateStore()

    tool = build_configured_jira_tool(store, settings)
    if tool is None:
        print(
            "Jira connector is not configured -- set JIRA_BASE_URL / JIRA_EMAIL / "
            "JIRA_API_TOKEN in .env. See .env.example."
        )
        return

    if not tool.health_check():
        print("Jira connector health check failed -- check your .env and API token.")
        return
    print("Health check OK.\n")

    if not args:
        jql = DEFAULT_JQL
        print(f"Running JQL: {jql}\n")
        for issue in tool.search_issues(process_id="demo", jql=jql, max_results=DEFAULT_MAX_RESULTS):
            print(f"- {issue.issue_type or '?'} {issue.issue_key}: {issue.fields.get('summary')}")
        return

    command, *rest = args
    if command == "--search":
        jql = rest[0]
        print(f"Running JQL: {jql}\n")
        for issue in tool.search_issues(process_id="demo", jql=jql):
            print(f"- {issue.issue_type or '?'} {issue.issue_key}: {issue.fields.get('summary')}")
    elif command == "--read":
        (issue_key,) = rest
        issue = tool.get_issue(process_id="demo", issue_key=issue_key)
        print(f"{issue.issue_type} {issue.issue_key}: {issue.fields.get('summary')}")
    elif command == "--create":
        project_key, summary, issue_type = rest
        fields = {"project": {"key": project_key}, "summary": summary, "issuetype": {"name": issue_type}}
        result = tool.create_issue(process_id="demo", fields=fields, dry_run=True)
        print(f"[dry run] executed={result.executed} {result.description}: {result.details}")
    elif command == "--update":
        issue_key, *field_pairs = rest
        result = tool.update_issue(
            process_id="demo", issue_key=issue_key, fields=_parse_fields(field_pairs), dry_run=True
        )
        print(f"[dry run] executed={result.executed} {result.description}: {result.details}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
