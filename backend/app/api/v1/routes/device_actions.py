"""Panel endpoints to run catalogue actions with the PIN (ADR-021).

Web parity for Telegram actions: the owner can trigger an action and approve it with the
same PIN from the browser, then read the result here. Same core (request_action +
approve_with_pin); no new approval path, no new power.
"""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from app.api.v1.routes.auth import (
    _INVALID_MESSAGE,
    _NO_STORE_HEADERS,
    _UNAVAILABLE_MESSAGE,
    _AuthRequest,
    _generic_json_response,
    _origin_is_acceptable,
    _run_sync,
    _runtime,
)
from app.api.v1.routes.telegram import _principal
from app.auth.abuse_control import AbuseControlKey
from app.devices import commands

device_actions_router = APIRouter(prefix="/devices", tags=["devices"])

# Only actions that take no argument are offered from the panel (send_file needs a file name
# and its own flow). Must stay a subset of the ADR-016 catalogue.
WEB_ACTIONS = frozenset({"lock_screen", "webcam_photo", "network_scan"})


class ActionRequest(_AuthRequest):
    kind: str
    pin: str = Field(min_length=6, max_length=6)


async def _require_principal(request: Request) -> uuid.UUID | Response:
    try:
        principal = await _principal(request)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if principal is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    return principal.user_id


@device_actions_router.post("/{device_id}/actions")
async def start_action(device_id: uuid.UUID, body: ActionRequest, request: Request) -> Response:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime):
        return _generic_json_response(403, _INVALID_MESSAGE)
    user_id = await _require_principal(request)
    if isinstance(user_id, Response):
        return user_id
    if body.kind not in WEB_ACTIONS:
        return _generic_json_response(400, _INVALID_MESSAGE)
    key = AbuseControlKey.from_settings(runtime.settings)
    try:
        command_id, check = await _run_sync(
            lambda: commands.start_web_action(
                runtime.session_factory,
                key,
                user_id=user_id,
                device_id=device_id,
                kind=body.kind,
                pin=body.pin,
            )
        )
    except commands.DeviceNotFoundForUser:
        return _generic_json_response(404, "Computador não encontrado ou não está ativo.")
    except commands.TooManyOpenCommands:
        return _generic_json_response(409, "Você já tem pedidos em andamento. Aguarde terminarem.")
    except commands.UnknownAction:
        return _generic_json_response(400, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if command_id is None:
        if check.locked_until is not None:
            return JSONResponse(
                status_code=423,
                content={"code": "PIN_LOCKED", "locked_until": check.locked_until.isoformat()},
                headers=_NO_STORE_HEADERS,
            )
        # 422 (not 403): the panel's HTTP client treats 403 as a global auth error.
        return JSONResponse(
            status_code=422, content={"code": "WRONG_PIN"}, headers=_NO_STORE_HEADERS
        )
    return JSONResponse(
        status_code=202,
        content={"command_id": str(command_id)},
        headers=_NO_STORE_HEADERS,
    )


@device_actions_router.get("/{device_id}/actions/{command_id}")
async def action_status(
    device_id: uuid.UUID, command_id: uuid.UUID, request: Request
) -> Response:
    user_id = await _require_principal(request)
    if isinstance(user_id, Response):
        return user_id
    runtime = _runtime(request)
    try:
        result = await _run_sync(
            lambda: commands.web_action_status(
                runtime.session_factory,
                user_id=user_id,
                device_id=device_id,
                command_id=command_id,
            )
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if result is None:
        return _generic_json_response(404, _INVALID_MESSAGE)
    return JSONResponse(
        status_code=200,
        content={
            "status": result.status,
            "message": result.message,
            "text": result.text,
            "has_photo": result.has_photo,
        },
        headers=_NO_STORE_HEADERS,
    )


@device_actions_router.get("/{device_id}/actions/{command_id}/photo")
async def action_photo(
    device_id: uuid.UUID, command_id: uuid.UUID, request: Request
) -> Response:
    user_id = await _require_principal(request)
    if isinstance(user_id, Response):
        return user_id
    runtime = _runtime(request)
    try:
        photo = await _run_sync(
            lambda: commands.web_action_photo(
                runtime.session_factory,
                user_id=user_id,
                device_id=device_id,
                command_id=command_id,
            )
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if photo is None:
        return _generic_json_response(404, _INVALID_MESSAGE)
    return Response(
        content=photo,
        media_type="image/jpeg",
        headers={**_NO_STORE_HEADERS, "Content-Disposition": "inline"},
    )
