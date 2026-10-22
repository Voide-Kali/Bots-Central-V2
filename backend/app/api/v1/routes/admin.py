"""Admin endpoints (ADR-017). Non-admins get the same 404 as an unknown route."""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.admin import service
from app.api.v1.routes.auth import (
    _NO_STORE_HEADERS,
    _UNAVAILABLE_MESSAGE,
    _generic_json_response,
    _origin_is_acceptable,
    _run_sync,
    _runtime,
)
from app.api.v1.routes.telegram import _principal
from app.auth import authentication

admin_router = APIRouter(prefix="/admin", tags=["admin"])


def _hidden() -> Response:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


async def _admin(request: Request) -> authentication.AuthenticatedPrincipal | None:
    principal = await _principal(request)
    return principal if principal is not None and principal.role == "admin" else None


async def _read(request: Request, query: Callable[[Any], Any], key: str) -> Response:
    try:
        if await _admin(request) is None:
            return _hidden()
        runtime = _runtime(request)

        def load() -> Any:
            with runtime.session_factory() as session:
                return query(session)

        data = await _run_sync(load)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(status_code=200, content={key: data}, headers=_NO_STORE_HEADERS)


@admin_router.get("/overview")
async def overview(request: Request) -> Response:
    return await _read(request, service.overview, "overview")


@admin_router.get("/users")
async def users(request: Request) -> Response:
    return await _read(request, service.list_users, "users")


@admin_router.get("/failures")
async def failures(request: Request) -> Response:
    return await _read(request, service.recent_failures, "failures")


@admin_router.get("/audit")
async def audit_events(request: Request) -> Response:
    return await _read(request, service.recent_audit, "events")


@admin_router.post("/users/{user_id}/activate")
async def activate(user_id: str, request: Request) -> Response:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime):
        return _hidden()
    try:
        admin = await _admin(request)
        if admin is None:
            return _hidden()
        target = uuid.UUID(user_id)
        await _run_sync(
            lambda: service.activate_user(
                runtime.session_factory, admin_id=admin.user_id, user_id=target
            )
        )
    except (ValueError, service.NotFound):
        return _hidden()
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return Response(status_code=204, headers=_NO_STORE_HEADERS)
