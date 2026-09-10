"""Public anonymous email-verification HTTP boundary."""

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

import anyio
from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import authentication
from app.auth import email_verification_application as application
from app.auth.abuse_control import (
    AbuseControlKey,
    AbuseController,
    AbuseControlUnavailable,
    ClientAddressUnavailable,
    InvalidAbuseControlConfiguration,
    client_network,
)
from app.auth.email_verification_consume import (
    AlreadyConsumed,
    AlreadyVerified,
    ConsumedEmailVerification,
    EmailVerificationConsumeOutcome,
)
from app.auth.email_verification_delivery import (
    DeliveryIntent,
    EmailVerificationDeliveryAdapter,
    SmtpEmailVerificationDeliveryAdapter,
    dispatch_delivery,
)
from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationHmacConfiguration,
)
from app.auth.emails import EmailValidationError, validate_and_canonicalize_email
from app.auth.passwords import PasswordPolicyError
from app.core.config import Settings
from app.db.enums import EmailVerificationMaterialType
from app.db.models import Device
from app.db.session import get_engine

auth_router = APIRouter(prefix="/auth", tags=["auth"])
devices_router = APIRouter(prefix="/devices", tags=["devices"])
verification_page_router = APIRouter()

_AUTH_BODY_LIMITS = {
    "/api/v1/auth/register": 8 * 1024,
    "/api/v1/auth/email-verification/resend": 1024,
    "/api/v1/auth/email-verification/consume-code": 1024,
    "/api/v1/auth/email-verification/consume-link": 1024,
    "/api/v1/auth/login": 8 * 1024,
}
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_ACCEPTED_MESSAGE = "If eligible, verification instructions will be sent."
_INVALID_MESSAGE = "Invalid request."
_UNAVAILABLE_MESSAGE = "Request temporarily unavailable."

SessionFactory = Callable[[], Session]
T = TypeVar("T")


class AuthRequestSecurityMiddleware:
    """Bound and buffer tiny anonymous-auth JSON bodies before route validation."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] not in _AUTH_BODY_LIMITS:
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope["headers"]
        }
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            await _generic_json_response(415, _INVALID_MESSAGE)(scope, receive, send)
            return
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > _AUTH_BODY_LIMITS[scope["path"]]:
                    await _generic_json_response(413, _INVALID_MESSAGE)(scope, receive, send)
                    return
            except ValueError:
                await _generic_json_response(400, _INVALID_MESSAGE)(scope, receive, send)
                return
        body_parts: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body = message.get("body", b"")
            total += len(body)
            if total > _AUTH_BODY_LIMITS[scope["path"]]:
                await _generic_json_response(413, _INVALID_MESSAGE)(scope, receive, send)
                return
            body_parts.append(body)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay_receive() -> dict[str, object]:
            nonlocal consumed
            if consumed:
                return {"type": "http.request", "body": b"", "more_body": False}
            consumed = True
            return {"type": "http.request", "body": b"".join(body_parts), "more_body": False}

        await self.app(scope, replay_receive, send)


@dataclass
class AuthHttpRuntime:
    """Process-local wiring; database admission remains the shared authority."""

    session_factory: SessionFactory
    abuse_controller: AbuseController | None
    keyring: EmailVerificationHmacKeyring | None
    delivery_adapter: EmailVerificationDeliveryAdapter | None
    settings: Settings
    password_limiter: anyio.CapacityLimiter

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuthHttpRuntime":
        factory = sessionmaker(bind=get_engine())
        try:
            abuse_controller: AbuseController | None = AbuseController(
                factory, AbuseControlKey.from_settings(settings)
            )
        except InvalidAbuseControlConfiguration:
            abuse_controller = None
        try:
            keyring = EmailVerificationHmacKeyring.from_settings(settings)
        except InvalidEmailVerificationHmacConfiguration:
            keyring = None
        delivery_adapter: EmailVerificationDeliveryAdapter | None = None
        if settings.email_verification_delivery_mode == "smtp":
            delivery_adapter = SmtpEmailVerificationDeliveryAdapter.from_settings(settings)
        return cls(
            session_factory=factory,
            abuse_controller=abuse_controller,
            keyring=keyring,
            delivery_adapter=delivery_adapter,
            settings=settings,
            password_limiter=anyio.CapacityLimiter(settings.argon2_max_concurrency),
        )


class _AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegistrationRequest(_AuthRequest):
    email: str = Field(max_length=320)
    password: SecretStr

    @field_validator("password")
    @classmethod
    def password_size(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 1024:
            raise ValueError("password is too long")
        return value


class ResendRequest(_AuthRequest):
    email: str = Field(max_length=320)


class ConsumeCodeRequest(_AuthRequest):
    challenge_id: uuid.UUID
    code: str = Field(max_length=9)


class ConsumeLinkRequest(_AuthRequest):
    token: SecretStr

    @field_validator("token")
    @classmethod
    def token_size(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 43:
            raise ValueError("token is too long")
        return value


class LoginRequest(_AuthRequest):
    email: str = Field(max_length=320)
    password: SecretStr

    @field_validator("password")
    @classmethod
    def password_size(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) > 1024:
            raise ValueError("password is too long")
        return value


def _generic_json_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"message": message}, headers=_NO_STORE_HEADERS
    )


def _consume_outcome_response(outcome: EmailVerificationConsumeOutcome) -> JSONResponse:
    """Expose only verified success, never the reason a normal consume failed."""
    if isinstance(outcome, ConsumedEmailVerification | AlreadyConsumed | AlreadyVerified):
        return JSONResponse(status_code=200, content={"verified": True}, headers=_NO_STORE_HEADERS)
    return JSONResponse(status_code=400, content={"verified": False}, headers=_NO_STORE_HEADERS)


async def generic_validation_error(_: Request, __: Exception) -> JSONResponse:
    """Never expose Pydantic's rejected input in public auth responses."""
    return _generic_json_response(422, _INVALID_MESSAGE)


def configure_auth_http(app: FastAPI, settings: Settings) -> None:
    app.state.auth_runtime = AuthHttpRuntime.from_settings(settings)
    app.add_middleware(AuthRequestSecurityMiddleware)
    app.add_exception_handler(RequestValidationError, generic_validation_error)


def _runtime(request: Request) -> AuthHttpRuntime:
    return cast(AuthHttpRuntime, request.app.state.auth_runtime)


def _network(request: Request, runtime: AuthHttpRuntime) -> str:
    if request.client is None:
        raise ClientAddressUnavailable("public request has no usable peer address")
    return client_network(
        request.client.host,
        trusted_proxy_ip=runtime.settings.trusted_proxy_ip,
        forwarded_for=tuple(request.headers.getlist("x-forwarded-for")),
    )


def _origin_is_acceptable(request: Request, runtime: AuthHttpRuntime) -> bool:
    origin = request.headers.get("origin")
    return origin is None or (
        runtime.settings.public_origin is not None and origin == runtime.settings.public_origin
    )


def _web_cookie_request_is_acceptable(request: Request, runtime: AuthHttpRuntime) -> bool:
    """Require browser evidence for endpoints that issue or consume the refresh cookie.

    Native clients need a future, separately authenticated refresh boundary; absence
    of Origin is not accepted on this same-origin web-cookie boundary.
    """
    if runtime.settings.public_origin is None:
        return False
    if request.headers.get("origin") != runtime.settings.public_origin:
        return False
    fetch_site = request.headers.get("sec-fetch-site")
    return fetch_site in {None, "same-origin"}


async def _admit(operation: Callable[[], bool]) -> bool | None:
    try:
        return await anyio.to_thread.run_sync(operation)
    except AbuseControlUnavailable:
        return None


async def _run_sync[T](operation: Callable[[], T]) -> T:
    return await anyio.to_thread.run_sync(operation)


def _schedule_delivery(
    background_tasks: BackgroundTasks,
    adapter: EmailVerificationDeliveryAdapter,
    intent: DeliveryIntent | None,
) -> None:
    if intent is not None:
        background_tasks.add_task(dispatch_delivery, adapter, intent)


def _material_type(runtime: AuthHttpRuntime) -> EmailVerificationMaterialType:
    return EmailVerificationMaterialType(runtime.settings.email_verification_material_type)


def _auth_ready_for_issuance(runtime: AuthHttpRuntime) -> bool:
    return runtime.abuse_controller is not None and runtime.delivery_adapter is not None


@auth_router.post("/register", status_code=202)
async def register(
    body: RegistrationRequest, request: Request, background_tasks: BackgroundTasks
) -> Response:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime) or not _auth_ready_for_issuance(runtime):
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        canonical = validate_and_canonicalize_email(body.email)
        network = _network(request, runtime)
    except EmailValidationError:
        return _generic_json_response(422, _INVALID_MESSAGE)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    controller = runtime.abuse_controller
    assert controller is not None
    admitted = await _admit(
        lambda: controller.admit_registration(canonical_email=canonical.canonical, network=network)
    )
    if admitted is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    if _material_type(runtime) is EmailVerificationMaterialType.CODE and runtime.keyring is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        result = await anyio.to_thread.run_sync(
            lambda: application.register_and_stage_email_verification(
                runtime.session_factory,
                email=body.email,
                password=body.password.get_secret_value(),
                material_type=_material_type(runtime),
                keyring=runtime.keyring,
            ),
            limiter=runtime.password_limiter,
        )
    except PasswordPolicyError:
        return _generic_json_response(422, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    adapter = runtime.delivery_adapter
    assert adapter is not None
    _schedule_delivery(background_tasks, adapter, result.delivery_intent)
    return _generic_json_response(202, _ACCEPTED_MESSAGE)


@auth_router.post("/email-verification/resend", status_code=202)
async def resend(
    body: ResendRequest, request: Request, background_tasks: BackgroundTasks
) -> Response:
    runtime = _runtime(request)
    if not _origin_is_acceptable(request, runtime) or not _auth_ready_for_issuance(runtime):
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        canonical = validate_and_canonicalize_email(body.email)
        network = _network(request, runtime)
    except EmailValidationError:
        return _generic_json_response(422, _INVALID_MESSAGE)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    controller = runtime.abuse_controller
    assert controller is not None
    admitted = await _admit(
        lambda: controller.admit_resend(canonical_email=canonical.canonical, network=network)
    )
    if admitted is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    if _material_type(runtime) is EmailVerificationMaterialType.CODE and runtime.keyring is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        result = await _run_sync(
            lambda: application.resend_email_verification(
                runtime.session_factory,
                email=body.email,
                material_type=_material_type(runtime),
                keyring=runtime.keyring,
            )
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    adapter = runtime.delivery_adapter
    assert adapter is not None
    _schedule_delivery(background_tasks, adapter, result.delivery_intent)
    return _generic_json_response(202, _ACCEPTED_MESSAGE)


@auth_router.post("/email-verification/consume-code")
async def consume_code(body: ConsumeCodeRequest, request: Request) -> Response:
    runtime = _runtime(request)
    controller = runtime.abuse_controller
    keyring = runtime.keyring
    if not _origin_is_acceptable(request, runtime) or controller is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if keyring is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        network = _network(request, runtime)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    admitted = await _admit(
        lambda: controller.admit_code_consume(challenge_id=body.challenge_id, network=network)
    )
    if admitted is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    try:
        result = await _run_sync(
            lambda: application.consume_email_verification_code_application(
                runtime.session_factory,
                challenge_id=body.challenge_id,
                code=body.code,
                keyring=keyring,
            )
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return _consume_outcome_response(result.outcome)


@auth_router.post("/email-verification/consume-link")
async def consume_link(body: ConsumeLinkRequest, request: Request) -> Response:
    runtime = _runtime(request)
    controller = runtime.abuse_controller
    if not _origin_is_acceptable(request, runtime) or controller is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    try:
        network = _network(request, runtime)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    admitted = await _admit(lambda: controller.admit_link_consume(network=network))
    if admitted is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    try:
        result = await _run_sync(
            lambda: application.consume_email_verification_link_application(
                runtime.session_factory, external_token=body.token.get_secret_value()
            )
        )
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return _consume_outcome_response(result.outcome)


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        return None
    token = value[7:]
    return token if token and len(token) <= 43 else None


def _set_refresh_cookie(
    response: JSONResponse, runtime: AuthHttpRuntime, refresh_token: SecretStr
) -> None:
    response.set_cookie(
        "refresh_token",
        refresh_token.get_secret_value(),
        httponly=True,
        secure=runtime.settings.app_env == "production",
        samesite="strict",
        max_age=30 * 24 * 3600,
        path="/api/v1/auth",
    )


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request) -> Response:
    runtime = _runtime(request)
    if not _web_cookie_request_is_acceptable(request, runtime):
        return _generic_json_response(403, _INVALID_MESSAGE)
    if runtime.abuse_controller is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    controller = runtime.abuse_controller
    assert controller is not None
    try:
        canonical = validate_and_canonicalize_email(body.email)
        network = _network(request, runtime)
    except EmailValidationError:
        return _generic_json_response(422, _INVALID_MESSAGE)
    except ClientAddressUnavailable:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    admitted = await _admit(
        lambda: controller.admit_login(
            canonical_email=canonical.canonical, network=network
        )
    )
    if admitted is None:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not admitted:
        return _generic_json_response(429, _UNAVAILABLE_MESSAGE)
    try:
        result = await anyio.to_thread.run_sync(
            lambda: authentication.login(
                runtime.session_factory,
                email=body.email,
                password=body.password.get_secret_value(),
            ),
            limiter=runtime.password_limiter,
        )
    except authentication.InvalidCredentials:
        return _generic_json_response(401, "Invalid credentials.")
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    response = JSONResponse(
        status_code=200,
        content={
            "access_token": result.access_token.get_secret_value(),
            "token_type": "Bearer",
            "expires_in": result.access_expires_in,
        },
        headers=_NO_STORE_HEADERS,
    )
    _set_refresh_cookie(response, runtime, result.refresh_token)
    return response


@auth_router.post("/refresh")
async def refresh(request: Request) -> Response:
    runtime = _runtime(request)
    if not _web_cookie_request_is_acceptable(request, runtime):
        return _generic_json_response(403, _INVALID_MESSAGE)
    token = request.cookies.get("refresh_token")
    if token is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    try:
        result = await _run_sync(lambda: authentication.refresh(runtime.session_factory, token))
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    if not result.success or result.access_token is None or result.refresh_token is None:
        response = _generic_json_response(401, _INVALID_MESSAGE)
        response.delete_cookie("refresh_token", path="/api/v1/auth")
        return response
    response = JSONResponse(
        status_code=200,
        content={
            "access_token": result.access_token.get_secret_value(),
            "token_type": "Bearer",
            "expires_in": result.access_expires_in,
        },
        headers=_NO_STORE_HEADERS,
    )
    _set_refresh_cookie(response, runtime, result.refresh_token)
    return response


@auth_router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    runtime = _runtime(request)
    if not _web_cookie_request_is_acceptable(request, runtime):
        return _generic_json_response(403, _INVALID_MESSAGE)
    token = _bearer(request)
    if token:
        try:
            await _run_sync(lambda: authentication.logout(runtime.session_factory, token))
        except Exception:
            return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    response = Response(status_code=204, headers=_NO_STORE_HEADERS)
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return response


@auth_router.get("/me")
async def me(request: Request) -> Response:
    token = _bearer(request)
    if token is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    runtime = _runtime(request)
    try:
        principal = await _run_sync(
            lambda: authentication.authenticate_access(runtime.session_factory, token)
        )
    except authentication.InvalidAccessToken:
        return _generic_json_response(401, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(
        status_code=200,
        content={"id": str(principal.user_id), "email": principal.email},
        headers=_NO_STORE_HEADERS,
    )


@devices_router.get("")
async def devices(request: Request) -> Response:
    token = _bearer(request)
    if token is None:
        return _generic_json_response(401, _INVALID_MESSAGE)
    runtime = _runtime(request)
    try:
        principal = await _run_sync(
            lambda: authentication.authenticate_access(runtime.session_factory, token)
        )
        with runtime.session_factory() as session:
            rows = session.scalars(
                select(Device)
                .where(Device.user_id == principal.user_id)
                .order_by(Device.created_at, Device.id)
            ).all()
            payload = [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "platform": item.platform,
                    # Presence is deliberately conservative until a heartbeat contract
                    # and server-side threshold are frozen: all devices are offline.
                    "status": "offline",
                    "lifecycle_status": item.lifecycle_status.value,
                    "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
                    "agent_version": item.agent_version,
                }
                for item in rows
            ]
    except authentication.InvalidAccessToken:
        return _generic_json_response(401, _INVALID_MESSAGE)
    except Exception:
        return _generic_json_response(503, _UNAVAILABLE_MESSAGE)
    return JSONResponse(status_code=200, content={"devices": payload}, headers=_NO_STORE_HEADERS)


@verification_page_router.get("/email-verification", include_in_schema=False)
async def verification_page(request: Request) -> Response:
    if request.url.query:
        return Response(status_code=404, headers=_NO_STORE_HEADERS)
    nonce = secrets.token_urlsafe(24)
    content = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Email verification</title></head>
<body><main><h1>Email verification</h1><p id="status">Open a verification link to continue.</p>
<button id="verify" type="button" disabled>Verify email</button></main>
<script nonce="{nonce}">
(() => {{
  const hash = window.location.hash;
  history.replaceState(null, "", window.location.pathname);
  const match = /^#token=([A-Za-z0-9_-]{{43}})$/.exec(hash);
  let token = match ? match[1] : null;
  const button = document.getElementById("verify");
  const status = document.getElementById("status");
  if (token) {{ button.disabled = false; status.textContent = "Confirm email verification."; }}
  button.addEventListener("click", async () => {{
    if (!token) return;
    button.disabled = true;
    try {{
      const response = await fetch("/api/v1/auth/email-verification/consume-link", {{
        method: "POST", credentials: "omit", headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{token}})
      }});
      const payload = await response.json().catch(() => null);
      status.textContent = response.ok && payload && payload.verified === true
        ? "Email verified."
        : "Verification could not be completed.";
    }} catch (_) {{
      status.textContent = "Verification could not be completed.";
    }} finally {{
      token = null;
    }}
  }});
}})();
</script></body></html>"""
    headers = {
        **_NO_STORE_HEADERS,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'none'; "
            f"script-src 'nonce-{nonce}'; "
            "connect-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'none'"
        ),
    }
    return HTMLResponse(content=content, headers=headers)
