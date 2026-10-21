"""Signed agent endpoints for human-approved commands (ADR-015)."""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, SecretStr

from app.api.v1.routes.auth import (
    _INVALID_MESSAGE,
    _NO_STORE_HEADERS,
    _UNAVAILABLE_MESSAGE,
    _admit,
    _AuthRequest,
    _generic_json_response,
    _network,
    _run_sync,
    _runtime,
)
from app.auth import device_online
from app.auth.abuse_control import ClientAddressUnavailable
from app.devices import commands

device_commands_router = APIRouter(prefix="/devices", tags=["devices"])


class SignedRequest(_AuthRequest):
    jws: SecretStr = Field(max_length=8192)


class ResultRequest(_AuthRequest):
    jws: SecretStr = Field(max_length=8192)
    content_b64: str | None = Field(default=None, max_length=15 * 1024 * 1024)


def _limited() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"code": "HEARTBEAT_RATE_LIMITED"},
        headers={**_NO_STORE_HEADERS, "Retry-After": "60"},
    )


async def _admit_device(request: Request, device_id: uuid.UUID) -> Response | None:
    runtime = _runtime(request)
    controller = runtime.abuse_controller
    if controller is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        network = _network(request, runtime)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    for check in (
        lambda: controller.admit_heartbeat_preauth(network=network),
        lambda: controller.admit_heartbeat(device_id=device_id),
    ):
        admitted = await _admit(check)
        if admitted is None:
            return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
        if not admitted:
            return _limited()
    return None


def _device_error(error: Exception) -> Response:
    if isinstance(error, device_online.DeviceRevoked):
        return JSONResponse(
            status_code=403, content={"code": "DEVICE_REVOKED"}, headers=_NO_STORE_HEADERS
        )
    if isinstance(error, device_online.DevicePending):
        return JSONResponse(
            status_code=403, content={"code": "DEVICE_PENDING"}, headers=_NO_STORE_HEADERS
        )
    if isinstance(error, device_online.StaleHeartbeat):
        return JSONResponse(
            status_code=409, content={"code": "STALE_HEARTBEAT"}, headers=_NO_STORE_HEADERS
        )
    if isinstance(error, (device_online.DeviceNotFound, device_online.InvalidProof)):
        return _generic_json_response(401, _INVALID_MESSAGE)
    if isinstance(error, commands.CommandError):
        return _generic_json_response(409, _INVALID_MESSAGE)
    return _generic_json_response(503, _UNAVAILABLE_MESSAGE)


@device_commands_router.post("/{device_id}/commands/next")
async def next_command(device_id: uuid.UUID, body: SignedRequest, request: Request) -> Response:
    denied = await _admit_device(request, device_id)
    if denied is not None:
        return denied
    runtime = _runtime(request)
    try:
        command = await _run_sync(
            lambda: commands.next_command(
                runtime.session_factory, device_id=device_id, jws=body.jws.get_secret_value()
            )
        )
    except Exception as error:
        return _device_error(error)
    return JSONResponse(status_code=200, content={"command": command}, headers=_NO_STORE_HEADERS)


@device_commands_router.post("/{device_id}/commands/{command_id}/result")
async def command_result(
    device_id: uuid.UUID, command_id: uuid.UUID, body: ResultRequest, request: Request
) -> Response:
    denied = await _admit_device(request, device_id)
    if denied is not None:
        return denied
    runtime = _runtime(request)
    try:
        await _run_sync(
            lambda: commands.submit_result(
                runtime.session_factory,
                device_id=device_id,
                command_id=command_id,
                jws=body.jws.get_secret_value(),
                content_b64=body.content_b64,
            )
        )
    except Exception as error:
        return _device_error(error)
    return JSONResponse(status_code=200, content={"accepted": True}, headers=_NO_STORE_HEADERS)
