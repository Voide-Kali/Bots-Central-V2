"""Owner-only read access to the caller's own audit trail."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1.routes.auth import (
    _INVALID_MESSAGE,
    _NO_STORE_HEADERS,
    _UNAVAILABLE_MESSAGE,
    _bearer,
    _generic_json_response,
    _run_sync,
    _runtime,
)
from app.audit import events as audit
from app.auth import authentication

audit_router = APIRouter(prefix="/audit", tags=["audit"])


@audit_router.get("")
async def list_events(request: Request) -> Response:
    token = _bearer(request)
    if token is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    raw = request.query_params.get("limit", "50")
    if not raw.isascii() or not raw.isdigit() or len(raw) > 3:
        return _generic_json_response(400, _INVALID_MESSAGE)
    limit = int(raw)
    if not 1 <= limit <= audit.MAX_LIST:
        return _generic_json_response(400, _INVALID_MESSAGE)
    runtime = _runtime(request)
    try:
        principal = await _run_sync(
            lambda: authentication.authenticate_access(runtime.session_factory, token)
        )

        def load() -> list[dict[str, object]]:
            with runtime.session_factory() as session:
                rows = audit.list_for_user(session, user_id=principal.user_id, limit=limit)
                return [audit.to_json(row) for row in rows]

        items = await _run_sync(load)
    except authentication.InvalidAccessToken:
        return _generic_json_response(401, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(status_code=200, content={"events": items}, headers=_NO_STORE_HEADERS)
