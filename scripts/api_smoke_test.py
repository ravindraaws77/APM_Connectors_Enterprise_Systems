"""Read-only smoke-test for the connector API, run directly against a
live server -- no Google/MS credentials needed, since this only
exercises the read routes (they just query the state store, never a
tool). Good first check that the API is up and reachable at all --
exactly what a reasoning/orchestration layer consuming this package
would do first too.

Setup (one-time):
  1. pip install -e ".[connectors]"
  2. In one terminal: uvicorn apm_connectors.api.app:app --reload --port 8000

Usage:
  python scripts/api_smoke_test.py
  python scripts/api_smoke_test.py --base-url http://127.0.0.1:8000
  python scripts/api_smoke_test.py --process-id order-123
  python scripts/api_smoke_test.py --api-key sk_abc123  # only if APM_API_KEYS is set on the server
"""

from __future__ import annotations

import argparse
import os
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--process-id", default=None, help="Also print status/history/pending for this process id")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("APM_CONNECTORS_API_KEY"),
        help="Bearer token, only needed against a server with APM_API_KEYS configured "
        "(defaults to APM_CONNECTORS_API_KEY; harmless to pass against a server with no auth configured)",
    )
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}

    ok = True
    ok &= _check("GET /health", lambda: requests.get(f"{args.base_url}/health", timeout=5))
    ok &= _check("GET /processes", lambda: requests.get(f"{args.base_url}/processes", headers=headers, timeout=5))

    if args.process_id:
        pid = args.process_id
        ok &= _check(
            f"GET /processes/{pid}/status",
            lambda: requests.get(f"{args.base_url}/processes/{pid}/status", headers=headers, timeout=5),
        )
        ok &= _check(
            f"GET /processes/{pid}/history",
            lambda: requests.get(f"{args.base_url}/processes/{pid}/history", headers=headers, timeout=5),
        )
        ok &= _check(
            f"GET /processes/{pid}/pending",
            lambda: requests.get(f"{args.base_url}/processes/{pid}/pending", headers=headers, timeout=5),
        )

    sys.exit(0 if ok else 1)


def _check(label: str, call) -> bool:
    """A reachable server that responds -- even with a 404 for an
    unknown process id, a legitimate answer, not a smoke-test failure
    -- counts as OK. A dropped connection, a 5xx (the server itself
    breaking), or a 401 (APM_API_KEYS is configured on the server and
    --api-key here is missing/wrong) counts as FAIL.
    """
    try:
        response = call()
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] {label}: could not connect -- is `uvicorn apm_connectors.api.app:app --port 8000` running?")
        return False

    if response.status_code == 401:
        print(f"[FAIL] {label}: HTTP 401 -- server has APM_API_KEYS configured; pass a valid --api-key")
        return False

    if response.status_code >= 500:
        print(f"[FAIL] {label}: HTTP {response.status_code} -- {response.text}")
        return False

    print(f"[ OK ] {label}: HTTP {response.status_code}")
    print(f"       {response.json()}")
    return True


if __name__ == "__main__":
    main()
