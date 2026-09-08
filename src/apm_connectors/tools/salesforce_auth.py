"""Salesforce auth helper for the Salesforce connector.

Uses the OAuth 2.0 Client Credentials Flow: a server-to-server exchange of
a Connected App's consumer key/secret for an access token, no interactive
user login involved. This is the deliberate choice over the older
Username-Password OAuth flow (deprecated by Salesforce) or a full
Authorization Code flow (needs a redirect/browser step this headless
package has no UI for) -- Client Credentials is the flow meant for exactly
this shape of automation, at the cost of the token being scoped to a
Connected App's "run as" user rather than a specific human's session (an
org admin decides that mapping when setting up the Connected App).

Access tokens from this flow are short-lived and cheap to re-request, so
there is no local token cache to manage here -- a fresh token is
requested each time a SalesforceTool is built.

`requests` is imported lazily so the rest of the codebase (and any test
that only exercises SalesforceTool's logic with a fake client) doesn't
need it installed at import time.
"""

from __future__ import annotations

from apm_connectors.config import Settings

DEFAULT_API_VERSION = "v60.0"


def acquire_access_token(settings: Settings) -> tuple[str, str]:
    """Return `(access_token, instance_url)` for the configured Connected
    App, using the OAuth 2.0 Client Credentials Flow.

    Requires SALESFORCE_CLIENT_ID / SALESFORCE_CLIENT_SECRET /
    SALESFORCE_DOMAIN to be set -- see .env.example for how to obtain them
    (Salesforce Setup -> App Manager -> New Connected App, with "Enable
    Client Credentials Flow" turned on and a run-as user assigned).
    """
    import requests

    if not settings.salesforce_client_id or not settings.salesforce_client_secret or not settings.salesforce_domain:
        raise RuntimeError(
            "SALESFORCE_CLIENT_ID / SALESFORCE_CLIENT_SECRET / SALESFORCE_DOMAIN are not set. "
            "See .env.example for how to obtain them from Salesforce Setup."
        )

    token_url = f"https://{settings.salesforce_domain}/services/oauth2/token"
    response = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": settings.salesforce_client_id,
            "client_secret": settings.salesforce_client_secret,
        },
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if "access_token" not in body or "instance_url" not in body:
        raise RuntimeError(f"Salesforce token response missing access_token/instance_url: {body}")
    return body["access_token"], body["instance_url"]
