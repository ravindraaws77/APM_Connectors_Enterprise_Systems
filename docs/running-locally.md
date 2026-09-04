# Running locally

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -e ".[dev]"
pytest -q
```

No credentials are needed to run the test suite — every connector is
tested against an in-memory fake client (see `tests/`).

## Run the API

```
uvicorn apm_connectors.api.app:app --reload --port 8000
```

Sanity check it's up:

```
python scripts/api_smoke_test.py
```

## Configure real connectors

Copy `.env.example` to `.env` and fill in whichever tools you want to
exercise for real — see `docs/capability-map.md` for what each one
needs. Every route works with fake clients (tests) with no `.env` at
all; real credentials are only needed to actually call Gmail/Calendar/
Excel.

## What this service is (and isn't)

This is the connector/enterprise-systems layer only — see
`docs/api-contract.md` for the full `/tools/*` contract. There's no
reasoning, no free-text entry point, no dashboard here: a reasoning or
orchestration layer is expected to be a separate deployment that calls
this API directly. See `docs/security-guardrails.md` for the one rule
that never bends regardless of who's calling: every write pauses for
human approval before anything executes.
