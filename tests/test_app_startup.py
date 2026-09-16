"""Confirms the API server fails at startup, not on its first request,
when DATABASE_URL is missing (api/app.py's `_lifespan`) -- so a load
balancer's /health check never reports "ok" for a server that can't
actually serve anything. Plain `TestClient(app)` never triggers FastAPI's
lifespan events (see tests/test_tools_api.py and friends, which all rely
on that to construct an app before overriding its dependencies); only
`with TestClient(app) as client:` does, which is what real ASGI servers
(uvicorn) use too.
"""

import pytest
from fastapi.testclient import TestClient

from apm_connectors.api.app import create_app


def test_server_refuses_to_start_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()

    with pytest.raises(RuntimeError, match="DATABASE_URL"), TestClient(app):
        pass
