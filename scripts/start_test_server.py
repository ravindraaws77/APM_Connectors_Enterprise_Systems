"""Start a throwaway apm_connectors API server that only ever uses test
configuration -- for apm_orchestrator's live mechanics tests
(tests/test_case_graph_mechanics.py, via its scripts/run_live_tests.py)
and scripts/e2e_smoke.py.

What it does, every run, whatever your .env says:
  - Excel points at a local test workbook (created with a "Renewals"
    sheet if it doesn't exist yet). APM_EXCEL_DRIVE_FILE_ID is blanked,
    so your real Drive workbook is never touched.
  - Every other live connector (Gmail/Calendar, Drive, Salesforce, Jira)
    is switched off, so its routes 503 -- this server can't reach a
    real external system at all.
  - APM_API_KEYS is replaced with two test callers (an orchestrator key
    and a human-approver key), so proposer and approver are distinct
    identities in the audit trail.
  - Listens on 127.0.0.1:8123 by default, clear of a normal :8000 server.

Your .env is read but never modified. Everything it sets that isn't
listed above (DATABASE_URL in particular) is used as usual.

Optional .env entries (all have defaults, none are required):
  APM_TEST_EXCEL_DIR=state/test             folder for the test workbook;
                                            relative paths are resolved
                                            against the repo root
  APM_TEST_EXCEL_FILE=test_workbook.xlsx    test workbook file name
  APM_TEST_SERVER_DATABASE_URL=             a separate database for this
                                            server (defaults to
                                            DATABASE_URL); keeps test
                                            records out of your real
                                            audit history
  APM_TEST_ORCHESTRATOR_KEY=orch-key        the two test API keys -- must
  APM_TEST_APPROVER_KEY=approver-key        match apm_orchestrator's
                                            run_live_tests.py

Usage:
  python scripts/start_test_server.py
  python scripts/start_test_server.py --port 8124
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_EXCEL_DIR = "state/test"
DEFAULT_EXCEL_FILE = "test_workbook.xlsx"
DEFAULT_ORCHESTRATOR_KEY = "orch-key"
DEFAULT_APPROVER_KEY = "approver-key"
DEFAULT_PORT = 8123

# Credentials for every connector besides Excel. Blanked (set to "",
# which python-dotenv then won't overwrite from .env, and which every
# build_configured_*_tool treats as unset) so the test server has no
# route to a real external system.
LIVE_CONNECTOR_VARS = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_TOKEN_JSON",
    "APM_DRIVE_FOLDER_ID",
    "SALESFORCE_CLIENT_ID",
    "SALESFORCE_CLIENT_SECRET",
    "SALESFORCE_DOMAIN",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
)


def _setting(name: str, dotenv: dict[str, str | None], default: str | None = None) -> str | None:
    """A shell-set value wins over .env, which wins over the default --
    the same precedence python-dotenv itself uses."""
    value = os.environ.get(name)
    if value:
        return value
    value = dotenv.get(name)
    if value:
        return value
    return default


def resolve_workbook_path(dotenv: dict[str, str | None], repo_root: Path = REPO_ROOT) -> Path:
    folder = Path(_setting("APM_TEST_EXCEL_DIR", dotenv, DEFAULT_EXCEL_DIR))
    if not folder.is_absolute():
        folder = repo_root / folder
    file_name = _setting("APM_TEST_EXCEL_FILE", dotenv, DEFAULT_EXCEL_FILE)
    if Path(file_name).name != file_name:
        raise SystemExit(
            f"APM_TEST_EXCEL_FILE must be a file name only, got {file_name!r} -- "
            "put the folder in APM_TEST_EXCEL_DIR instead."
        )
    if not file_name.lower().endswith(".xlsx"):
        raise SystemExit(f"APM_TEST_EXCEL_FILE must end in .xlsx, got {file_name!r}")
    return (folder / file_name).resolve()


def build_test_env(dotenv: dict[str, str | None], workbook: Path) -> dict[str, str]:
    """The environment overrides that make this a test-only server."""
    real_workbook = _setting("APM_EXCEL_WORKBOOK_PATH", dotenv)
    if real_workbook and Path(real_workbook).resolve() == workbook:
        raise SystemExit(
            f"The test workbook {workbook} is the same file as APM_EXCEL_WORKBOOK_PATH -- "
            "refusing to start. Point APM_TEST_EXCEL_DIR/APM_TEST_EXCEL_FILE somewhere else."
        )

    orchestrator_key = _setting("APM_TEST_ORCHESTRATOR_KEY", dotenv, DEFAULT_ORCHESTRATOR_KEY)
    approver_key = _setting("APM_TEST_APPROVER_KEY", dotenv, DEFAULT_APPROVER_KEY)
    if orchestrator_key == approver_key:
        raise SystemExit("APM_TEST_ORCHESTRATOR_KEY and APM_TEST_APPROVER_KEY must differ.")

    overrides = {name: "" for name in LIVE_CONNECTOR_VARS}
    overrides.update(
        {
            "APM_EXCEL_WORKBOOK_PATH": str(workbook),
            "APM_EXCEL_DRIVE_FILE_ID": "",
            "APM_API_KEYS": f"orchestrator:{orchestrator_key},human-approver:{approver_key}",
        }
    )
    test_db = _setting("APM_TEST_SERVER_DATABASE_URL", dotenv)
    if test_db:
        overrides["DATABASE_URL"] = test_db
    return overrides


def ensure_workbook(path: Path) -> bool:
    """Create the test workbook with a "Renewals" sheet if it's missing.
    Returns True if it was created."""
    if path.exists():
        return False
    import openpyxl

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.active.title = "Renewals"
    workbook.save(path)
    return True


def _disable_google_token_cache() -> None:
    """Blanking the Google env vars isn't enough on its own: Gmail/Calendar
    also load a cached token file (.google_token.json) if one exists from
    a past interactive login. Make that build step fail the same way an
    unconfigured Google setup does, so get_tools() leaves both out."""
    from apm_connectors.api import dependencies

    def _disabled(*_args, **_kwargs):
        raise RuntimeError("Gmail/Calendar are disabled on the test server")

    dependencies.build_gmail_and_calendar_tools = _disabled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")
    args = parser.parse_args()

    from dotenv import dotenv_values

    dotenv = dotenv_values(REPO_ROOT / ".env")
    workbook = resolve_workbook_path(dotenv)
    overrides = build_test_env(dotenv, workbook)

    # Must happen before anything imports apm_connectors.config: its
    # load_dotenv() never overwrites a variable that already exists, so
    # these values (blank ones included) win over .env.
    os.environ.update(overrides)

    created = ensure_workbook(workbook)
    database = "APM_TEST_SERVER_DATABASE_URL" if "DATABASE_URL" in overrides else "DATABASE_URL (from .env)"
    print("apm_connectors TEST server")
    print(f"  Excel workbook : {workbook}{'  (created)' if created else ''}")
    print("  Drive workbook : disabled")
    print("  Gmail/Calendar/Drive/Salesforce/Jira : disabled")
    print("  API keys       : orchestrator + human-approver test keys")
    print(f"  Database       : {database}")
    print(f"  Listening on   : http://127.0.0.1:{args.port}")
    sys.stdout.flush()

    _disable_google_token_cache()

    import uvicorn

    uvicorn.run("apm_connectors.api.app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
