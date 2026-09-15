"""Unit tests for the auth gate (apm_connectors.api.dependencies.
require_caller) and its config-parsing helper (apm_connectors.config.
_parse_api_keys) -- direct function calls, no HTTP/FastAPI app involved.
See tests/test_tools_api.py for the same gate exercised through real
routes.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from apm_connectors.api import dependencies as dependencies_module
from apm_connectors.api.dependencies import require_caller
from apm_connectors.config import _parse_api_keys


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_parse_api_keys_empty_or_none_means_disabled() -> None:
    assert _parse_api_keys(None) == {}
    assert _parse_api_keys("") == {}
    assert _parse_api_keys("   ") == {}


def test_parse_api_keys_single_pair() -> None:
    assert _parse_api_keys("alice:sk_abc123") == {"sk_abc123": "alice"}


def test_parse_api_keys_multiple_pairs_and_whitespace() -> None:
    assert _parse_api_keys(" alice:sk_abc123 , orchestrator:sk_def456 ") == {
        "sk_abc123": "alice",
        "sk_def456": "orchestrator",
    }


def test_parse_api_keys_rejects_malformed_entry() -> None:
    with pytest.raises(ValueError, match="Malformed APM_API_KEYS entry"):
        _parse_api_keys("alice")  # no ":key"

    with pytest.raises(ValueError, match="Malformed APM_API_KEYS entry"):
        _parse_api_keys("alice:")  # empty key

    with pytest.raises(ValueError, match="Malformed APM_API_KEYS entry"):
        _parse_api_keys(":sk_abc123")  # empty name


def test_require_caller_returns_none_when_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {})

    assert require_caller(credentials=None) is None
    # A stray token is simply ignored when auth is off entirely.
    assert require_caller(credentials=_creds("anything")) is None


def test_require_caller_401s_with_no_credentials_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})

    with pytest.raises(HTTPException) as exc_info:
        require_caller(credentials=None)
    assert exc_info.value.status_code == 401


def test_require_caller_401s_with_wrong_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice"})

    with pytest.raises(HTTPException) as exc_info:
        require_caller(credentials=_creds("wrong-token"))
    assert exc_info.value.status_code == 401


def test_require_caller_returns_caller_name_for_a_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dependencies_module, "get_api_keys", lambda: {"sk_abc123": "alice", "sk_def456": "orchestrator"}
    )

    assert require_caller(credentials=_creds("sk_abc123")) == "alice"
    assert require_caller(credentials=_creds("sk_def456")) == "orchestrator"
