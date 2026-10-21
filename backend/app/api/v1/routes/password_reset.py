"""Anonymous password recovery endpoints (ADR-014).

Both endpoints answer generically so an attacker cannot learn whether an
e-mail has an account. Delivery happens after the response, in the background.
"""

import logging

import anyio
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response
from pydantic import Field, SecretStr

from app.api.v1.routes.auth import (
    _INVALID_MESSAGE,
    _UNAVAILABLE_MESSAGE,
    _admit,
    _AuthRequest,
    _generic_json_response,
    _network,
    _origin_is_acceptable,
    _runtime,
)
from app.auth import password_reset
from app.auth.abuse_control import (
    AbuseControlKey,
    ClientAddressUnavailable,
    InvalidAbuseControlConfiguration,
)
from app.auth.emails import EmailValidationError, validate_and_canonicalize_email
from app.auth.passwords import PasswordPolicyError

password_reset_router = APIRouter(prefix="/auth/password-reset", tags=["auth"])
logger = logging.getLogger("bots_central.password_reset")

ACCEPTED = "If the account exists, a reset code was sent by e-mail."
DONE = "Password changed. Sign in again on every device."


class ResetRequest(_AuthRequest):
    email: str = Field(max_length=320)


class ResetConfirm(_AuthRequest):
    email: str = Field(max_length=320)
    code: str = Field(min_length=8, max_length=8)
    new_password: SecretStr


def _send(mailer: object, intent: password_reset.ResetIntent) -> None:
    send_plain = getattr(mailer, "send_plain", None)
    if send_plain is None:
        return
    code = intent.code.get_secret_value()
    try:
        send_plain(
            recipient=intent.recipient,
            subject="Aval — código para redefinir sua senha",
            body=(
                "Alguém pediu para redefinir a senha da sua conta no Aval.\n\n"
                f"Código: {code[:4]} {code[4:]}\n"
                "Ele vale por 15 minutos e só pode ser usado uma vez.\n\n"
                "Se não foi você, ignore este e-mail: sua senha continua a mesma.\n"
            ),
        )
    except Exception:
        logger.warning("password reset delivery failed")


async def _gate(request: Request, email: str, *, confirm: bool) -> tuple[str, Response | None]:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime) or runtime.abuse_controller is None:
        return "", _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        canonical = validate_and_canonicalize_email(email).canonical
        network = _network(request, runtime)
    except EmailValidationError:
        return "", _generic_json_response(422, _INVALID_MESSAGE)
    except ClientAddressUnavailable:
        return "", _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    controller = runtime.abuse_controller
    admit = (
        controller.admit_password_reset_confirm
        if confirm
        else controller.admit_password_reset_request
    )
    admitted = await _admit(lambda: admit(canonical_email=canonical, network=network))
    if admitted is None:
        return "", _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return "", _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    return canonical, None


def _key(request: Request) -> AbuseControlKey | None:
    try:
        return AbuseControlKey.from_settings(_runtime(request).settings)
    except InvalidAbuseControlConfiguration:
        return None


@password_reset_router.post("/request", status_code=202)
async def request_code(
    body: ResetRequest, request: Request, background_tasks: BackgroundTasks
) -> Response:
    _, denied = await _gate(request, body.email, confirm=False)
    if denied is not None:
        return denied
    runtime = _runtime(request)
    key = _key(request)
    if key is None or runtime.delivery_adapter is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        intent = await anyio.to_thread.run_sync(
            lambda: password_reset.request_reset(runtime.session_factory, key, email=body.email)
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if intent is not None:
        background_tasks.add_task(_send, runtime.delivery_adapter, intent)
    return _generic_json_response(202, ACCEPTED)


@password_reset_router.post("/confirm")
async def confirm(body: ResetConfirm, request: Request) -> Response:
    _, denied = await _gate(request, body.email, confirm=True)
    if denied is not None:
        return denied
    runtime = _runtime(request)
    key = _key(request)
    if key is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        changed = await anyio.to_thread.run_sync(
            lambda: password_reset.confirm_reset(
                runtime.session_factory,
                key,
                email=body.email,
                code=body.code,
                new_password=body.new_password.get_secret_value(),
            ),
            limiter=runtime.password_limiter,
        )
    except PasswordPolicyError:
        return _generic_json_response(422, "Password does not meet the policy.")
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not changed:
        return _generic_json_response(400, _INVALID_MESSAGE)
    return _generic_json_response(200, DONE)
