"""Manual smoke-test for the Salesforce connector -- run this yourself once
you have a real Connected App with the Client Credentials Flow enabled; it
is not part of the automated test suite (those use a fake client, see
tests/test_salesforce_tool.py and tests/test_salesforce_auth.py).

Setup (one-time):
  1. Salesforce Setup -> App Manager -> New Connected App. Enable OAuth
     Settings, check "Enable Client Credentials Flow", and assign a run-as
     user under Policies -> Client Credentials Flow (Setup -> Company
     Settings -> My Domain gives you the domain for step 2).
  2. Copy .env.example to .env and fill in SALESFORCE_CLIENT_ID /
     SALESFORCE_CLIENT_SECRET / SALESFORCE_DOMAIN.
  3. pip install -e ".[connectors]"

Usage:
  # Health check + a default SOQL query against Organization:
  python scripts/salesforce_demo.py

  # A SOQL query of your choice:
  python scripts/salesforce_demo.py --query "SELECT Id, Name FROM Account LIMIT 5"

  # Read a single record by object + id:
  python scripts/salesforce_demo.py --read Account 001XXXXXXXXXXXXXXX

  # Exercise create/update -- ALWAYS dry_run here (this script never sets
  # dry_run=False; a real write is only ever safe from inside the action
  # graph's execute_node after a human-approval interrupt, see
  # .claude/skills/tool-integration/SKILL.md). This just proves the call
  # shape and logging work against a real access token.
  python scripts/salesforce_demo.py --create Lead LastName=Doe Company=Acme
  python scripts/salesforce_demo.py --update Lead 00QXXXXXXXXXXXXXXX Company=Acme2

This only ever performs read calls against the org, plus dry-run (no-op)
create/update calls -- nothing is written to Salesforce.
"""

from __future__ import annotations

import sys

from apm_connectors.config import load_settings
from apm_connectors.state.store import StateStore
from apm_connectors.tools.salesforce_tool import build_configured_salesforce_tool

DEFAULT_QUERY = "SELECT Id, Name FROM Organization LIMIT 1"


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

    tool = build_configured_salesforce_tool(store, settings)
    if tool is None:
        print(
            "Salesforce connector is not configured -- set SALESFORCE_CLIENT_ID / "
            "SALESFORCE_CLIENT_SECRET / SALESFORCE_DOMAIN in .env. See .env.example."
        )
        return

    if not tool.health_check():
        print("Salesforce connector health check failed -- check your .env and Connected App setup.")
        return
    print("Health check OK.\n")

    if not args:
        soql = DEFAULT_QUERY
        print(f"Running SOQL: {soql}\n")
        for record in tool.query_records(process_id="demo", soql=soql):
            print(f"- {record.object_type or '?'} {record.record_id}: {record.fields}")
        return

    command, *rest = args
    if command == "--query":
        soql = rest[0]
        print(f"Running SOQL: {soql}\n")
        for record in tool.query_records(process_id="demo", soql=soql):
            print(f"- {record.object_type or '?'} {record.record_id}: {record.fields}")
    elif command == "--read":
        object_name, record_id = rest
        record = tool.get_record(process_id="demo", object_name=object_name, record_id=record_id)
        print(f"{record.object_type} {record.record_id}: {record.fields}")
    elif command == "--create":
        object_name, *field_pairs = rest
        result = tool.create_record(
            process_id="demo", object_name=object_name, fields=_parse_fields(field_pairs), dry_run=True
        )
        print(f"[dry run] executed={result.executed} {result.description}: {result.details}")
    elif command == "--update":
        object_name, record_id, *field_pairs = rest
        result = tool.update_record(
            process_id="demo",
            object_name=object_name,
            record_id=record_id,
            fields=_parse_fields(field_pairs),
            dry_run=True,
        )
        print(f"[dry run] executed={result.executed} {result.description}: {result.details}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
