"""Small ASGI contract tests for the public Device Online boundary."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Never

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.routes import auth as auth_route
from app.auth import authentication, device_online
from app.core.config import Settings
from app.main import create_app


class DeviceAdmission:
    def __init__(self, *, preauth: bool = True, device: bool = True) -> None:
        self.preauth = preauth
        self.device = device

    def admit_heartbeat_preauth(self, *, network: str) -> bool:
        return self.preauth

    def admit_heartbeat(self, *, device_id: uuid.UUID) -> bool:
        return self.device

    def admit_enrollment_preauth(self, *, network: str) -> bool:
        return self.preauth


def unreachable_session_factory() -> Never:
    raise AssertionError("database must not be reached in this boundary test")


def app_with_runtime(admission: DeviceAdmission) -> FastAPI:
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=unreachable_session_factory,
        abuse_controller=admission,  # type: ignore[arg-type]
        keyring=None,
        delivery_adapter=None,
        settings=Settings(public_origin="http://localhost:8000"),
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_pairing_enrollment_approval_and_reject_http_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = app_with_runtime(DeviceAdmission())
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@example.com")
    device_id = uuid.uuid4()
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)
    monkeypatch.setattr(
        device_online,
        "create_pairing",
        lambda *_args, **_kwargs: device_online.Pairing(
            uuid.uuid4(), "P" * 43, datetime.now(UTC) + timedelta(minutes=5)
        ),
    )
    monkeypatch.setattr(
        device_online,
        "enroll",
        lambda *_args, **_kwargs: device_online.Enrollment(device_id, "SHA256:" + "x" * 43),
    )
    approved: list[str] = []
    monkeypatch.setattr(
        device_online, "approve", lambda *_args, **kwargs: approved.append(kwargs["fingerprint"])
    )
    monkeypatch.setattr(
        device_online, "reject", lambda *_args, **kwargs: approved.append(kwargs["fingerprint"])
    )
    async with await _client(app) as client:
        unauthorized = await client.post("/api/v1/devices/pairings", json={})
        pairing = await client.post(
            "/api/v1/devices/pairings",
            json={},
            headers={"Authorization": "Bearer " + "A" * 43},
        )
        enrollment = await client.post(
            "/api/v1/devices/enrollments",
            json={
                "pairing_token": "P" * 43,
                "public_key": "K" * 43,
                "proof": "proof",
                "name": "agent",
                "platform": "linux",
            },
        )
        approve = await client.post(
            f"/api/v1/devices/{device_id}/approve",
            json={"fingerprint": "SHA256:" + "x" * 43},
            headers={"Authorization": "Bearer " + "A" * 43},
        )
        reject = await client.post(
            f"/api/v1/devices/{device_id}/reject",
            json={"fingerprint": "SHA256:" + "x" * 43},
            headers={"Authorization": "Bearer " + "A" * 43},
        )
        oversized = await client.post(
            "/api/v1/devices/pairings",
            content=b"x" * 1025,
            headers={"Content-Type": "application/json"},
        )
    assert unauthorized.status_code == 401
    assert pairing.status_code == 201
    assert pairing.json()["pairing_token"] == "P" * 43
    assert pairing.json()["pairing_id"]
    assert "digest" not in pairing.text
    assert pairing.headers["cache-control"] == "no-store"
    assert enrollment.status_code == 201 and enrollment.json()["lifecycle_status"] == "pending"
    assert enrollment.json()["fingerprint"].startswith("SHA256:")
    assert enrollment.headers["cache-control"] == "no-store"
    assert approve.status_code == reject.status_code == 200
    assert len(approved) == 2
    assert oversized.status_code == 413


@pytest.mark.anyio
async def test_enrollment_preauth_denial_precedes_signature_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = app_with_runtime(DeviceAdmission(preauth=False))

    def forbidden(*_: object, **__: object) -> Never:
        raise AssertionError("enrollment signature verification must not run after pre-auth denial")

    monkeypatch.setattr(device_online, "enroll", forbidden)
    async with await _client(app) as client:
        response = await client.post(
            "/api/v1/devices/enrollments",
            json={
                "pairing_token": "P" * 43,
                "public_key": "K" * 43,
                "proof": "x",
                "name": "a",
                "platform": "linux",
            },
        )
    assert response.status_code == 429
    assert response.json() == {"message": "Request temporarily unavailable."}


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["approve", "reject"])
async def test_approve_reject_body_limit_precedes_mutation(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    app = app_with_runtime(DeviceAdmission())
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@example.com")
    called = 0
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)

    def mutate(*_: object, **__: object) -> None:
        nonlocal called
        called += 1

    monkeypatch.setattr(device_online, operation, mutate)
    path = f"/api/v1/devices/{uuid.uuid4()}/{operation}"
    async with await _client(app) as client:
        valid = await client.post(
            path,
            json={"fingerprint": "x"},
            headers={"Authorization": "Bearer " + "A" * 43},
        )
        oversized = await client.post(
            path,
            content=b"x" * 1025,
            headers={"Authorization": "Bearer " + "A" * 43, "Content-Type": "application/json"},
        )
    assert valid.status_code == 200
    assert oversized.status_code == 413
    assert called == 1


@pytest.mark.anyio
async def test_preauth_denial_skips_device_lookup_and_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = app_with_runtime(DeviceAdmission(preauth=False))
    called = False

    def forbidden(*_: object, **__: object) -> Never:
        nonlocal called
        called = True
        raise AssertionError("pre-auth denial must precede device authentication")

    monkeypatch.setattr(device_online, "authenticate_heartbeat", forbidden)
    async with await _client(app) as client:
        response = await client.post(
            f"/api/v1/devices/{uuid.uuid4()}/heartbeat", json={"jws": "invalid"}
        )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert not called


@pytest.mark.anyio
async def test_postauth_limit_prevents_heartbeat_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    app = app_with_runtime(DeviceAdmission(device=False))
    authenticated = False
    mutated = False

    def valid(*_: object, **__: object) -> None:
        nonlocal authenticated
        authenticated = True

    def forbidden(*_: object, **__: object) -> Never:
        nonlocal mutated
        mutated = True
        raise AssertionError("post-auth denial must precede heartbeat update")

    monkeypatch.setattr(device_online, "authenticate_heartbeat", valid)
    monkeypatch.setattr(device_online, "heartbeat", forbidden)
    async with await _client(app) as client:
        response = await client.post(
            f"/api/v1/devices/{uuid.uuid4()}/heartbeat", json={"jws": "valid"}
        )
    assert response.status_code == 429
    assert authenticated and not mutated
