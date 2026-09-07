"""Tests for the GOOGLE_TOKEN_JSON path in google_auth.load_credentials --
the headless-deployment alternative to the interactive browser consent
flow, added for the ECS Fargate deploy (infra/aws/ecs-fargate), which has
no browser and can't catch the flow's localhost redirect. No live Google
credentials or network access needed: a syntactically valid authorized-
user token dict is enough for google-auth to build a Credentials object
without ever calling out to Google.
"""

from __future__ import annotations

import json
from pathlib import Path

from apm_connectors.config import load_settings
from apm_connectors.tools.google_auth import load_credentials

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_FAKE_TOKEN_INFO = {
    "token": "fake-access-token",
    "refresh_token": "fake-refresh-token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "scopes": _SCOPES,
    # Credentials.from_authorized_user_info treats a missing "expiry" as
    # already-expired, which would otherwise make load_credentials try a
    # real (network) refresh call against Google with these fake values.
    "expiry": "2099-01-01T00:00:00Z",
}


def test_google_token_json_env_takes_precedence_and_skips_the_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", json.dumps(_FAKE_TOKEN_INFO))
    settings = load_settings()
    token_path = tmp_path / "should-not-be-touched.json"

    creds = load_credentials(settings, scopes=_SCOPES, token_path=token_path)

    assert creds.token == "fake-access-token"
    assert not token_path.exists()


def test_no_google_token_json_env_falls_back_to_the_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_TOKEN_JSON", raising=False)
    settings = load_settings()
    token_path = tmp_path / "cached-token.json"
    token_path.write_text(json.dumps(_FAKE_TOKEN_INFO))

    creds = load_credentials(settings, scopes=_SCOPES, token_path=token_path)

    assert creds.token == "fake-access-token"
