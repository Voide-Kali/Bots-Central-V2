"""Authenticated web endpoints to link and unlink a Telegram chat (ADR-011)."""

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
from app.auth import authentication
from app.telegram import linking

telegram_router = APIRouter(prefix="/telegram", tags=["telegram"])


async def _principal(request: Request) -> authentication.AuthenticatedPrincipal | None:
    token = _bearer(request)
    if token is None:
        return None
    runtime = _runtime(request)
    try:
        return await _run_sync(
            lambda: authentication.authenticate_access(runtime.session_factory, token)
        )
    except authentication.InvalidAccessToken:
        return None


@telegram_router.post("/link-code")
async def create_link_code(request: Request) -> Response:
    try:
        principal = await _principal(request)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if principal is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    runtime = _runtime(request)
    try:
        code = await _run_sync(
            lambda: linking.create_link_code(runtime.session_factory, user_id=principal.user_id)
        )
    except linking.InvalidLinkCode:
        return _generic_json_response(403, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(
        status_code=201,
        content={
            "code": code.code,
            "expires_at": code.expires_at.isoformat(),
            "bot_username": runtime.settings.telegram_bot_username,
        },
        headers=_NO_STORE_HEADERS,
    )


@telegram_router.get("/link")
async def link_status(request: Request) -> Response:
    try:
        principal = await _principal(request)
        if principal is None:
            return _generic_json_response(401, _INVALID_MESSAGE)
        runtime = _runtime(request)
        linked = await _run_sync(
            lambda: linking.is_linked(runtime.session_factory, user_id=principal.user_id)
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(
        status_code=200,
        content={"linked": linked, "bot_username": runtime.settings.telegram_bot_username},
        headers=_NO_STORE_HEADERS,
    )


@telegram_router.delete("/link", status_code=204)
async def unlink(request: Request) -> Response:
    try:
        principal = await _principal(request)
        if principal is None:
            return _generic_json_response(401, _INVALID_MESSAGE)
        runtime = _runtime(request)
        await _run_sync(
            lambda: linking.unlink_user(runtime.session_factory, user_id=principal.user_id)
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return Response(status_code=204, headers=_NO_STORE_HEADERS)
