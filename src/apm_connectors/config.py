"""Environment/config loading. No secrets ever live in this file.

Trimmed from the original apm.config: no ANTHROPIC_API_KEY/ANTHROPIC_MODEL
here — this package has no reasoning/Claude dependency at all, only the
connectors and the small propose/approval/execute LangGraph layer that
gates their writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is a dev convenience; absence just means the caller
    # is expected to export env vars some other way (shell, CI secrets, ...).
    pass

STATE_DIR = Path(os.environ.get("APM_STATE_DIR", "state"))


@dataclass(frozen=True)
class Settings:
    """Snapshot of the environment variables this package cares about.

    Values are read lazily via `load_settings()` rather than at import
    time, so tests can monkeypatch `os.environ` before calling it.
    """

    google_client_id: str | None
    google_client_secret: str | None
    excel_workbook_path: str | None
    excel_drive_file_id: str | None
    state_dir: Path
    # Default None so existing code that constructs Settings(...) directly
    # (e.g. test fixtures predating this field) doesn't break -- a dataclass
    # field with a default must come after every field without one.
    google_token_json: str | None = None
    salesforce_client_id: str | None = None
    salesforce_client_secret: str | None = None
    salesforce_domain: str | None = None
    salesforce_api_version: str | None = None
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    # Reuses GOOGLE_CLIENT_ID/SECRET (or GOOGLE_TOKEN_JSON) above -- see
    # tools/drive_tool.py's module docstring for why this is the only
    # setting needed to enable it (no separate "enabled" flag).
    drive_folder_id: str | None = None
    # Durable state, opt-in: when set, apm_connectors.api.dependencies
    # swaps the default file-backed StateStore + in-memory LangGraph
    # checkpointer for Postgres-backed ones (state/postgres_store.py) --
    # see docs/deployment.md's "State is ephemeral" known limitation.
    # A standard "postgresql://user:pass@host:port/dbname" URL. Requires
    # the optional `postgres` extra (`pip install -e ".[postgres]"`).
    database_url: str | None = None
    # API auth, opt-in like every other setting above: {key: caller_name},
    # parsed from APM_API_KEYS. Empty (unset) means auth is off -- every
    # /tools/* and /processes/* route behaves exactly as before (see
    # docs/api-contract.md's "No auth today"). See api/dependencies.py's
    # require_caller for how this is enforced, and this module's
    # _parse_api_keys for the "name:key,name:key" format.
    api_keys: dict[str, str] = field(default_factory=dict)


def _parse_api_keys(raw: str | None) -> dict[str, str]:
    """Parses APM_API_KEYS="name1:key1,name2:key2" into {key: name} --
    keyed by the token a caller actually presents (Authorization: Bearer
    <key>), so require_caller can look one up in O(1) and attribute it
    to a human-readable name in the audit trail. Unset/empty -> {} (auth
    disabled entirely, the local-dev default).
    """
    if not raw:
        return {}
    keys: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, key = entry.partition(":")
        if not sep or not name or not key:
            raise ValueError(f"Malformed APM_API_KEYS entry {entry!r} -- expected \"name:key\"")
        keys[key] = name
    return keys


def load_settings() -> Settings:
    return Settings(
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        google_token_json=os.environ.get("GOOGLE_TOKEN_JSON"),
        excel_workbook_path=os.environ.get("APM_EXCEL_WORKBOOK_PATH"),
        excel_drive_file_id=os.environ.get("APM_EXCEL_DRIVE_FILE_ID"),
        state_dir=STATE_DIR,
        salesforce_client_id=os.environ.get("SALESFORCE_CLIENT_ID"),
        salesforce_client_secret=os.environ.get("SALESFORCE_CLIENT_SECRET"),
        salesforce_domain=os.environ.get("SALESFORCE_DOMAIN"),
        salesforce_api_version=os.environ.get("SALESFORCE_API_VERSION"),
        jira_base_url=os.environ.get("JIRA_BASE_URL"),
        jira_email=os.environ.get("JIRA_EMAIL"),
        jira_api_token=os.environ.get("JIRA_API_TOKEN"),
        drive_folder_id=os.environ.get("APM_DRIVE_FOLDER_ID"),
        database_url=os.environ.get("DATABASE_URL"),
        api_keys=_parse_api_keys(os.environ.get("APM_API_KEYS")),
    )
