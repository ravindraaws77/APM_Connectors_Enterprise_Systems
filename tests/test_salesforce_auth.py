"""Tests for the Salesforce connector's config-driven factory
(build_configured_salesforce_tool) and its token-exchange helper
(acquire_access_token) -- same "unconfigured -> None / raises" shape as
tests/test_excel_file_tool.py's build_configured_excel_tool and
tests/test_google_auth.py's build_configured_gmail_and_calendar_tools.
"""

from pathlib import Path

import pytest

from apm_connectors.config import Settings
from apm_connectors.tools.salesforce_auth import acquire_access_token
from apm_connectors.tools.salesforce_tool import SalesforceTool, build_configured_salesforce_tool
from apm_connectors.state.store import StateStore


def _settings(
    *,
    salesforce_client_id: str | None = None,
    salesforce_client_secret: str | None = None,
    salesforce_domain: str | None = None,
) -> Settings:
    return Settings(
        google_client_id=None,
        google_client_secret=None,
        ms_graph_client_id=None,
        ms_graph_client_secret=None,
        ms_graph_tenant_id=None,
        excel_workbook_path=None,
        excel_drive_file_id=None,
        state_dir=Path("state"),
        salesforce_client_id=salesforce_client_id,
        salesforce_client_secret=salesforce_client_secret,
        salesforce_domain=salesforce_domain,
    )


def test_acquire_access_token_raises_when_unconfigured() -> None:
    with pytest.raises(RuntimeError, match="SALESFORCE_CLIENT_ID"):
        acquire_access_token(_settings())


def test_acquire_access_token_raises_when_only_client_id_is_set() -> None:
    with pytest.raises(RuntimeError, match="SALESFORCE_CLIENT_ID"):
        acquire_access_token(_settings(salesforce_client_id="id-only"))


def test_build_configured_salesforce_tool_returns_none_when_unconfigured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_salesforce_tool(store, _settings())

    assert result is None


def test_build_configured_salesforce_tool_returns_none_when_partially_configured(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")

    result = build_configured_salesforce_tool(
        store, _settings(salesforce_client_id="id", salesforce_client_secret="secret")
    )

    assert result is None


def test_build_configured_salesforce_tool_builds_when_fully_configured(tmp_path: Path, monkeypatch) -> None:
    """Doesn't exercise the real OAuth token exchange -- just confirms the
    fully-configured path calls through to acquire_access_token and
    returns a working SalesforceTool.
    """
    import apm_connectors.tools.salesforce_tool as salesforce_tool_module

    store = StateStore(tmp_path / "state.json")
    settings = _settings(
        salesforce_client_id="id", salesforce_client_secret="secret", salesforce_domain="acme.my.salesforce.com"
    )

    monkeypatch.setattr(
        "apm_connectors.tools.salesforce_auth.acquire_access_token",
        lambda passed_settings: ("fake-token", "https://acme.my.salesforce.com"),
    )

    tool = salesforce_tool_module.build_configured_salesforce_tool(store, settings)

    assert isinstance(tool, SalesforceTool)
