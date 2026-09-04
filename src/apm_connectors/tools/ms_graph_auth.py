"""Microsoft Graph auth helper for the Excel connector.

Uses MSAL's device-code flow: no local redirect server needed (works well
from a CLI script or a headless container), matching the same "installed
app" spirit as google_auth.py's flow for Gmail/Calendar. Only a public
client (app registration's client ID + tenant ID) is required — the
device-code flow doesn't use a client secret, unlike a confidential-client
(server-side) flow.

MSAL is imported lazily so the rest of the codebase (and any test that
only exercises ExcelTool's logic with a fake client) doesn't need it
installed.
"""

from __future__ import annotations

from pathlib import Path

from apm_connectors.config import Settings

DEFAULT_TOKEN_CACHE_PATH = Path(".ms_graph_token_cache.json")
GRAPH_AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}"


def acquire_access_token(
    settings: Settings,
    scopes: list[str],
    token_cache_path: Path = DEFAULT_TOKEN_CACHE_PATH,
) -> str:
    """Return a valid Microsoft Graph access token for the given delegated
    scopes (e.g. `["Files.Read"]`), using a cached token if possible, or
    the device-code flow otherwise: this prints a URL and a short code to
    the console for you to complete sign-in in a browser.

    `token_cache_path` is a local, gitignored file (see .gitignore's
    `*token*.json` pattern) — never commit it, it grants account access.
    """
    import msal

    if not settings.ms_graph_client_id or not settings.ms_graph_tenant_id:
        raise RuntimeError(
            "MS_GRAPH_CLIENT_ID / MS_GRAPH_TENANT_ID are not set. "
            "See .env.example for how to obtain them from Azure Portal."
        )

    cache = msal.SerializableTokenCache()
    if token_cache_path.exists():
        cache.deserialize(token_cache_path.read_text())

    app = msal.PublicClientApplication(
        client_id=settings.ms_graph_client_id,
        authority=GRAPH_AUTHORITY_TEMPLATE.format(tenant_id=settings.ms_graph_tenant_id),
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to start Microsoft device-code flow: {flow}")
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

    if cache.has_state_changed:
        token_cache_path.write_text(cache.serialize())

    if not result or "access_token" not in result:
        error = (result or {}).get("error_description", "unknown error")
        raise RuntimeError(f"Failed to acquire Microsoft Graph token: {error}")

    return result["access_token"]
