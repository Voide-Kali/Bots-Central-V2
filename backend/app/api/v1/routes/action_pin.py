"""Authenticated endpoints to set and inspect the action PIN (ADR-016 addendum)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, SecretStr

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
from app.auth import action_pin
from app.auth.abuse_control import AbuseControlKey

action_pin_router = APIRouter(prefix="/me/action-pin", tags=["auth"])


class PinUpdate(_AuthRequest):
    password: SecretStr
    pin: str = Field(min_length=6, max_length=6)


@action_pin_router.get("")
async def pin_status(request: Request) -> Response:
    try:
        principal = await _principal(request)
        if principal is None:
            return _generic_json_response(401, _INVALID_MESSAGE)
        runtime = _runtime(request)

        def load() -> tuple[bool, str | None]:
            with runtime.session_factory() as session:
                configured, locked = action_pin.status(session, principal.user_id)
                return configured, locked.isoformat() if locked else None

        configured, locked_until = await _run_sync(load)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(
        status_code=200,
        content={"configured": configured, "locked_until": locked_until},
        headers=_NO_STORE_HEADERS,
    )


@action_pin_router.put("")
async def set_pin(body: PinUpdate, request: Request) -> Response:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime):
        return _generic_json_response(403, _INVALID_MESSAGE)
    try:
        principal = await _principal(request)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if principal is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    try:
        key = AbuseControlKey.from_settings(runtime.settings)
        await _run_sync(
            lambda: action_pin.set_pin(
                runtime.session_factory,
                key,
                user_id=principal.user_id,
                password=body.password.get_secret_value(),
                pin=body.pin,
            )
        )
    except action_pin.PinPolicyError:
        return _generic_json_response(422, "PIN inválido: use 6 números que não sejam óbvios.")
    except action_pin.WrongPassword:
        return _generic_json_response(403, "Senha incorreta.")
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return Response(status_code=204, headers=_NO_STORE_HEADERS)
