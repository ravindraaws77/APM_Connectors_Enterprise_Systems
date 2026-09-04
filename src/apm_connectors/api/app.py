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

from fastapi import Depends, FastAPI, HTTPException

from apm_connectors.api.dependencies import get_state_store
from apm_connectors.api.tools_routes import router as tools_router
from apm_connectors.state.store import StateStore


def create_app() -> FastAPI:
    app = FastAPI(title="APM Connectors & Enterprise Systems API")
    app.include_router(tools_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/processes")
    def list_processes(store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_processes()

    @app.get("/processes/{process_id}/status")
    def get_process_status(process_id: str, store: StateStore = Depends(get_state_store)) -> dict:
        status = store.get_status(process_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown process_id: {process_id}")
        return status

    @app.get("/processes/{process_id}/history")
    def get_process_history(process_id: str, store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_events(process_id)

    @app.get("/processes/{process_id}/pending")
    def get_pending_actions(process_id: str, store: StateStore = Depends(get_state_store)) -> list[dict]:
        return store.list_pending_actions(process_id)

    return app


app = create_app()
