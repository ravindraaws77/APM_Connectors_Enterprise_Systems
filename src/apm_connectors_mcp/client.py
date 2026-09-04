"""Thin async HTTP client for apm_connectors' /tools/* API -- the only
thing apm_connectors_mcp talks to. Deliberately dumb: it never imports
apm_connectors.tools/graph directly, so this package can run anywhere
with just httpx + mcp installed, against a /tools/* server deployed
wherever -- matching this connector layer's own "consumed by a
reasoning layer, deployed separately" framing (docs/api-contract.md).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class ConnectorAPIError(Exception):
    """Raised for any non-2xx response from the /tools/* API. Carries
    the upstream status code and detail message through untouched --
    apm_connectors.api._responses already turns tool/graph failures
    into clean 503/502/422 responses with a readable `detail`; this
    just surfaces that to the caller instead of swallowing it.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ConnectorClient:
    """`base_url` defaults to APM_CONNECTORS_BASE_URL (falling back to
    the same 127.0.0.1:8000 docs/running-locally.md uses). `transport`
    is a testing hook -- pass an `httpx.ASGITransport` wrapping
    apm_connectors.api.app's FastAPI app directly to exercise this
    client (and the tools built on it) against real route handlers
    with no live server process or network involved, same spirit as
    tests/test_tools_api.py's in-process TestClient.
    """

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url or os.environ.get("APM_CONNECTORS_BASE_URL", DEFAULT_BASE_URL),
            timeout=30.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        response = await self._client.post(path, json=body)
        if response.status_code >= 400:
            raise ConnectorAPIError(response.status_code, _extract_detail(response))
        return response.json()


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        return detail if isinstance(detail, str) else str(detail)
    return str(payload)
