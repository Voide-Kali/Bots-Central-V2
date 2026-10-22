"""Telemetry carried in signed heartbeats (ADR-012): parsing, storage, and HTTP boundary."""

import base64
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.routes import auth as auth_route
from app.auth import authentication, device_online
from app.core.config import Settings
from app.db.enums import AccountStatus, AuthenticationLevel
from app.db.models import Device, DevicePairingToken, DeviceTelemetrySample, User
from app.db.models import Session as DbSession
from app.devices import telemetry
from app.main import create_app

VALID: dict[str, Any] = {
    "v": 1,
    "cpu_pct": 12.5,
    "load1": 0.42,
    "cpus": 8,
    "mem_total": 16 * 1024**3,
    "mem_used": 6 * 1024**3,
    "disk_total": 256 * 1000**3,
    "disk_used": 100 * 1000**3,
    "temp_c": 48.0,
    "uptime_s": 3600,
}


# --- parsing (no database) -------------------------------------------------------------


def test_valid_claim_parses_every_field() -> None:
    sample = telemetry.parse_claim(VALID)
    assert sample.cpu_percent == 12.5
    assert sample.cpu_count == 8
    assert sample.memory_used_bytes == 6 * 1024**3
    assert sample.temperature_c == 48.0


def test_minimal_claim_and_nulls_are_accepted() -> None:
    assert telemetry.parse_claim({"v": 1}) == telemetry.TelemetrySample()
    assert telemetry.parse_claim({"v": 1, "temp_c": None, "cpu_pct": None}).temperature_c is None


def test_battery_fields_parse() -> None:
    sample = telemetry.parse_claim({"v": 1, "battery_pct": 42, "battery_charging": True})
    assert sample.battery_percent == 42
    assert sample.battery_charging is True
    absent = telemetry.parse_claim({"v": 1})
    assert absent.battery_percent is None and absent.battery_charging is None


@pytest.mark.parametrize(
    "claim",
    [
        None,
        [],
        "x",
        {},
        {"v": 2},
        {"v": True},
        {"v": 1, "unknown": 1},
        {"v": 1, "cpu_pct": 101},
        {"v": 1, "cpu_pct": -1},
        {"v": 1, "cpu_pct": "10"},
        {"v": 1, "cpu_pct": float("nan")},
        {"v": 1, "cpus": 0},
        {"v": 1, "cpus": 1.5},
        {"v": 1, "cpus": True},
        {"v": 1, "mem_total": 10},
        {"v": 1, "mem_total": 10, "mem_used": 11},
        {"v": 1, "disk_total": 1 << 63, "disk_used": 0},
        {"v": 1, "temp_c": 151},
        {"v": 1, "uptime_s": -1},
        {"v": 1, "battery_pct": 101},
        {"v": 1, "battery_pct": -1},
        {"v": 1, "battery_pct": 50.0},
        {"v": 1, "battery_pct": True},
        {"v": 1, "battery_charging": 1},
        {"v": 1, "battery_charging": "yes"},
    ],
)
def test_invalid_claims_are_rejected(claim: object) -> None:
    with pytest.raises(telemetry.InvalidTelemetry):
        telemetry.parse_claim(claim)


# --- HTTP boundary (no database) -------------------------------------------------------


class _NullSession:
    def __enter__(self) -> "_NullSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _app() -> FastAPI:
    app = create_app()
    app.state.auth_runtime = auth_route.AuthHttpRuntime(
        session_factory=_NullSession,  # type: ignore[arg-type]
        abuse_controller=None,
        keyring=None,
        delivery_adapter=None,
        settings=Settings(public_origin="http://localhost:8000"),
        password_limiter=anyio.CapacityLimiter(1),
    )
    return app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t")


@pytest.mark.anyio
async def test_history_route_requires_auth_and_bounds_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@example.com")
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)
    device_id = uuid.uuid4()
    path = f"/api/v1/devices/{device_id}/telemetry"
    bearer = {"Authorization": "Bearer " + "A" * 43}
    async with await _client() as client:
        assert (await client.get(path)).status_code == 401
        for bad in ("0", "1441", "-5", "abc", "1e3", "٣"):
            response = await client.get(path, params={"minutes": bad}, headers=bearer)
            assert response.status_code == 400, bad


@pytest.mark.anyio
async def test_history_route_hides_devices_of_other_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = authentication.AuthenticatedPrincipal(uuid.uuid4(), uuid.uuid4(), "a@example.com")
    monkeypatch.setattr(authentication, "authenticate_access", lambda *_: principal)

    def not_owned(*_args: object, **_kwargs: object) -> list[DeviceTelemetrySample]:
        raise telemetry.DeviceNotOwned

    monkeypatch.setattr(telemetry, "history", not_owned)
    async with await _client() as client:
        response = await client.get(
            f"/api/v1/devices/{uuid.uuid4()}/telemetry",
            headers={"Authorization": "Bearer " + "A" * 43},
        )
    assert response.status_code == 404


# --- PostgreSQL ------------------------------------------------------------------------

_CREATED_USER_IDS: set[uuid.UUID] = set()


@pytest.fixture
def pg_cleanup(migrated_postgresql_engine: Engine) -> Generator[None, None, None]:
    _CREATED_USER_IDS.clear()
    try:
        yield
    finally:
        user_ids = tuple(_CREATED_USER_IDS)
        if user_ids:
            with Session(migrated_postgresql_engine) as session, session.begin():
                session.execute(
                    delete(DevicePairingToken).where(DevicePairingToken.user_id.in_(user_ids))
                )
                session.execute(delete(Device).where(Device.user_id.in_(user_ids)))
                session.execute(delete(DbSession).where(DbSession.user_id.in_(user_ids)))
                session.execute(delete(User).where(User.id.in_(user_ids)))
        _CREATED_USER_IDS.clear()


def _active_device(
    factory: sessionmaker[Session],
) -> tuple[uuid.UUID, uuid.UUID, Ed25519PrivateKey]:
    now = datetime.now(UTC)
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    _CREATED_USER_IDS.add(user_id)
    with factory() as session, session.begin():
        session.add(User(id=user_id, status=AccountStatus.ACTIVE, security_version=0))
        session.flush()
        session.add(
            DbSession(
                id=session_id,
                user_id=user_id,
                last_seen_at=now,
                expires_at=now + timedelta(days=1),
                idle_expires_at=now + timedelta(hours=1),
                security_version=0,
                authentication_level=AuthenticationLevel.PASSWORD_AUTHENTICATED,
                authentication_methods=["test"],
            )
        )
    pairing = device_online.create_pairing(factory, user_id=user_id, session_id=session_id)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    encoded = base64.urlsafe_b64encode(public).decode("ascii").rstrip("=")
    proof = jwt.encode(
        {"aud": device_online.ENROLLMENT_AUDIENCE, "sub": "e", "pairing_token": pairing.token},
        private,
        algorithm="EdDSA",
    )
    enrolled = device_online.enroll(
        factory,
        pairing_token=pairing.token,
        public_key_encoded=encoded,
        proof=proof,
        name="telemetry-agent",
        platform="linux",
        agent_version="0.1",
    )
    device_online.approve(
        factory, user_id=user_id, device_id=enrolled.device_id, fingerprint=enrolled.fingerprint
    )
    return user_id, enrolled.device_id, private


def _beat(private: Ed25519PrivateKey, device_id: uuid.UUID, seq: int, tel: object = None) -> str:
    claims: dict[str, object] = {
        "aud": device_online.HEARTBEAT_AUDIENCE,
        "sub": str(device_id),
        "seq": seq,
    }
    if tel is not None:
        claims["tel"] = tel
    return jwt.encode(claims, private, algorithm="EdDSA")


def _count(factory: sessionmaker[Session], device_id: uuid.UUID) -> int:
    with factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(DeviceTelemetrySample)
                .where(DeviceTelemetrySample.device_id == device_id)
            )
            or 0
        )


@pytest.mark.postgresql
@pytest.mark.usefixtures("pg_cleanup")
def test_heartbeat_stores_telemetry_and_latest_is_exposed(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    user_id, device_id, private = _active_device(factory)
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 1))
    assert _count(factory, device_id) == 0
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 2, VALID))
    newer = dict(VALID, cpu_pct=55.0)
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 3, newer))
    assert _count(factory, device_id) == 2
    with factory() as session:
        latest = telemetry.latest_for_devices(session, [device_id])
        assert latest[device_id].cpu_percent == 55.0
        rows = telemetry.history(session, user_id=user_id, device_id=device_id, minutes=60)
        assert [row.cpu_percent for row in rows] == [12.5, 55.0]
        with pytest.raises(telemetry.DeviceNotOwned):
            telemetry.history(session, user_id=uuid.uuid4(), device_id=device_id, minutes=60)


@pytest.mark.postgresql
@pytest.mark.usefixtures("pg_cleanup")
def test_invalid_telemetry_rejects_heartbeat_without_any_mutation(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    _, device_id, private = _active_device(factory)
    with pytest.raises(device_online.InvalidProof):
        device_online.authenticate_heartbeat(
            factory, device_id=device_id, jws=_beat(private, device_id, 1, {"v": 1, "cpus": 0})
        )
    with pytest.raises(device_online.InvalidProof):
        device_online.heartbeat(
            factory, device_id=device_id, jws=_beat(private, device_id, 1, {"v": 9})
        )
    with factory() as session:
        device = session.get(Device, device_id)
        assert device is not None
        assert device.last_seen_at is None and device.last_heartbeat_seq is None
    assert _count(factory, device_id) == 0


@pytest.mark.postgresql
@pytest.mark.usefixtures("pg_cleanup")
def test_replayed_heartbeat_does_not_store_telemetry_and_old_rows_are_pruned(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    _, device_id, private = _active_device(factory)
    signed = _beat(private, device_id, 5, VALID)
    device_online.heartbeat(factory, device_id=device_id, jws=signed)
    with pytest.raises(device_online.StaleHeartbeat):
        device_online.heartbeat(factory, device_id=device_id, jws=signed)
    assert _count(factory, device_id) == 1
    with factory() as session, session.begin():
        session.execute(
            update(DeviceTelemetrySample)
            .where(DeviceTelemetrySample.device_id == device_id)
            .values(recorded_at=func.clock_timestamp() - telemetry.RETENTION - timedelta(hours=1))
        )
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 6, VALID))
    assert _count(factory, device_id) == 1
