"""Small helpers shared by apm_connectors.api.app and
apm_connectors.api.tools_routes, so neither module has to import from
the other (both are wired into the FastAPI app in app.py's create_app).
"""

from __future__ import annotations

from fastapi import HTTPException

from apm_connectors.api.schemas import RunOutcomeResponse
from apm_connectors.graph import RunOutcome


def upstream_error(exc: Exception) -> HTTPException:
    """Turn an unexpected failure from the graph/a tool (a network error,
    an exhausted retry, an upstream API error, ...) into a clean 502
    response with a readable message, instead of letting an unhandled
    500 with a raw Python traceback reach the caller. Uvicorn still logs
    the full traceback server-side either way.
    """
    return HTTPException(status_code=502, detail=f"Upstream tool error: {exc}")


def to_response(outcome: RunOutcome) -> RunOutcomeResponse:
    return RunOutcomeResponse(
        process_id=outcome.process_id,
        summary=outcome.summary,
        pending_action=outcome.pending_action,
        final_result=outcome.final_result,
    )
