"""scripts/start_test_server.py's config logic: the test server must only
ever see test configuration, whatever the developer's .env says."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "start_test_server.py"
_spec = importlib.util.spec_from_file_location("start_test_server", _SCRIPT)
sts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sts)

_TEST_VARS = (
    "APM_TEST_EXCEL_DIR",
    "APM_TEST_EXCEL_FILE",
    "APM_TEST_SERVER_DATABASE_URL",
    "APM_TEST_ORCHESTRATOR_KEY",
    "APM_TEST_APPROVER_KEY",
    "APM_EXCEL_WORKBOOK_PATH",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _TEST_VARS:
        monkeypatch.delenv(name, raising=False)


def test_default_workbook_is_inside_the_repo(tmp_path):
    path = sts.resolve_workbook_path({}, repo_root=tmp_path)
    assert path == (tmp_path / "state" / "test" / "test_workbook.xlsx").resolve()


def test_dir_and_file_name_come_from_dotenv(tmp_path):
    dotenv = {"APM_TEST_EXCEL_DIR": "fixtures", "APM_TEST_EXCEL_FILE": "tracker.xlsx"}
    assert sts.resolve_workbook_path(dotenv, repo_root=tmp_path) == (tmp_path / "fixtures" / "tracker.xlsx").resolve()


def test_shell_value_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("APM_TEST_EXCEL_FILE", "from_shell.xlsx")
    path = sts.resolve_workbook_path({"APM_TEST_EXCEL_FILE": "from_dotenv.xlsx"}, repo_root=tmp_path)
    assert path.name == "from_shell.xlsx"


@pytest.mark.parametrize("bad", ["sub/x.xlsx", "x.csv"])
def test_rejects_a_bad_file_name(tmp_path, bad):
    with pytest.raises(SystemExit):
        sts.resolve_workbook_path({"APM_TEST_EXCEL_FILE": bad}, repo_root=tmp_path)


def test_overrides_blank_drive_and_every_live_connector(tmp_path):
    workbook = tmp_path / "t.xlsx"
    env = sts.build_test_env({"APM_EXCEL_DRIVE_FILE_ID": "real.xlsx", "JIRA_API_TOKEN": "real"}, workbook)
    assert env["APM_EXCEL_WORKBOOK_PATH"] == str(workbook)
    assert env["APM_EXCEL_DRIVE_FILE_ID"] == ""
    for name in sts.LIVE_CONNECTOR_VARS:
        assert env[name] == ""
    assert env["APM_API_KEYS"] == "orchestrator:orch-key,human-approver:approver-key"
    assert "DATABASE_URL" not in env


def test_separate_test_database_overrides_database_url(tmp_path):
    env = sts.build_test_env({"APM_TEST_SERVER_DATABASE_URL": "postgresql://localhost/t"}, tmp_path / "t.xlsx")
    assert env["DATABASE_URL"] == "postgresql://localhost/t"


def test_refuses_when_test_workbook_is_the_real_workbook(tmp_path):
    workbook = (tmp_path / "real.xlsx").resolve()
    with pytest.raises(SystemExit):
        sts.build_test_env({"APM_EXCEL_WORKBOOK_PATH": str(workbook)}, workbook)


def test_refuses_identical_keys(tmp_path):
    dotenv = {"APM_TEST_ORCHESTRATOR_KEY": "same", "APM_TEST_APPROVER_KEY": "same"}
    with pytest.raises(SystemExit):
        sts.build_test_env(dotenv, tmp_path / "t.xlsx")


def test_ensure_workbook_creates_renewals_sheet_once(tmp_path):
    import openpyxl

    path = tmp_path / "nested" / "t.xlsx"
    assert sts.ensure_workbook(path) is True
    assert openpyxl.load_workbook(path).sheetnames == ["Renewals"]
    assert sts.ensure_workbook(path) is False
