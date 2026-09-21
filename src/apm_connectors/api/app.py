"""FastAPI app: the HTTP surface over the connector layer
(apm_connectors.tools) and its small approval-gated action graph
(apm_connectors.graph). See docs/api-contract.md for the full contract.

Run it with: uvicorn apm_connectors.api.app:app --reload --port 8000

Routes never call a tool's write/action method directly or bypass the
graph's approval interrupt — every mutation goes through
POST /tools/actions/{id}/decision (apm_connectors.api.tools_routes),
which calls resume_process, which is the only path to execute_node.

This package has no reasoning of its own: there is no /query, no free-
text entry point, no LLM call anywhere in this process. A reasoning/
orchestration layer is expected to be deployed separately and call
/tools/* directly, deciding what to read and what write to propose.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from apm_connectors.api.dependencies import get_action_graph, get_state_store, require_caller
from apm_connectors.api.tools_routes import router as tools_router
from apm_connectors.logging_config import configure_logging
from apm_connectors.state.store import StateStoreProtocol

logger = logging.getLogger("apm_connectors.api")

# Every /processes/* route below sits behind require_caller too (never
# /health -- a load balancer's health check carries no credentials). See
# tools_routes.py's module docstring and api/dependencies.py's
# require_caller for what this does when APM_API_KEYS isn't configured.
_authenticated = [Depends(require_caller)]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Builds the action graph (which builds the state store and tools
    too) at startup, not on whatever request happens to land first --
    so `/health` never reports "ok" for a server that can't actually
    serve anything. Without DATABASE_URL this raises
    api.dependencies._require_database_url's clear RuntimeError before
    the server ever binds its port; with it set, this also catches an
    unreachable Postgres immediately rather than on the first real call.

    Goes through app.dependency_overrides (not the bare get_action_graph
    call a route's `Depends` would resolve to) so tests that override it
    with an in-memory fake (tests/integration/conftest.py's real-uvicorn
    fixtures) never need a real Postgres either -- exactly what a route
    handler gets when it depends on get_action_graph normally.
    """
    build_graph = app.dependency_overrides.get(get_action_graph, get_action_graph)
    build_graph()
    yield


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="APM Connectors & Enterprise Systems API", lifespan=_lifespan)
    app.include_router(tools_router)

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        """Structured (JSON) access log -- separate from the audit trail,
        which only ever sees /tools/* calls a route chose to log, and
        never sees timing or non-tools routes like /health."""
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/processes", dependencies=_authenticated)
    def list_processes(store: StateStoreProtocol = Depends(get_state_store)) -> list[dict]:
        return store.list_processes()

    @app.get("/processes/pending", dependencies=_authenticated)
    def list_all_pending_actions(store: StateStoreProtocol = Depends(get_state_store)) -> list[dict]:
        """Every pending action across every process, not just one --
        the single feed a human-approval UI or reviewer can poll without
        already knowing which process ids exist. Registered before the
        {process_id}/... routes below only for readability; FastAPI
        doesn't actually need the ordering since 'pending' here has no
        second path segment, so it can't collide with them.
        """
        return store.list_pending_actions()

    @app.get("/processes/{process_id}/status", dependencies=_authenticated)
    def get_process_status(process_id: str, store: StateStoreProtocol = Depends(get_state_store)) -> dict:
        status = store.get_status(process_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown process_id: {process_id}")
        return status

    @app.get("/processes/{process_id}/history", dependencies=_authenticated)
    def get_process_history(process_id: str, store: StateStoreProtocol = Depends(get_state_store)) -> list[dict]:
        return store.list_events(process_id)

    @app.get("/processes/{process_id}/pending", dependencies=_authenticated)
    def get_pending_actions(process_id: str, store: StateStoreProtocol = Depends(get_state_store)) -> list[dict]:
        return store.list_pending_actions(process_id)

    return app


app = create_app()
