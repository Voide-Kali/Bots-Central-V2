"""Device Online V0.1 pairing, approval, and signed heartbeat authority."""

import base64
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jwt import InvalidTokenError
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.db.enums import AccountStatus, DeviceLifecycleStatus
from app.db.models import Device, DevicePairingToken, User
from app.db.models import Session as DbSession
from app.devices import telemetry

SessionFactory = Callable[[], Session]
PAIRING_TOKEN_BYTES = 32
PAIRING_TTL = timedelta(minutes=5)
ENROLLMENT_AUDIENCE = "bots-central:enrollment:v1"
HEARTBEAT_AUDIENCE = "bots-central:heartbeat:v1"
ONLINE_WINDOW = timedelta(seconds=90)
MAX_SEQUENCE = (1 << 64) - 1


class InvalidPairing(Exception):
    pass


class PairingUnavailable(Exception):
    pass


class PairingNotFound(Exception):
    pass


class InvalidProof(Exception):
    pass


class DeviceNotFound(Exception):
    pass


class DeviceNotPending(Exception):
    pass


class FingerprintMismatch(Exception):
    pass


class DevicePending(Exception):
    pass


class DeviceRevoked(Exception):
    pass


class StaleHeartbeat(Exception):
    pass


@dataclass(frozen=True)
class Pairing:
    id: uuid.UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Enrollment:
    device_id: uuid.UUID
    fingerprint: str


def _clock(session: Session) -> datetime:
    return cast(datetime, session.scalar(text("SELECT clock_timestamp()")))


def _b64decode(value: str, *, expected_bytes: int) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise ValueError("invalid base64url value")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("invalid base64url value") from error
    if (
        len(decoded) != expected_bytes
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value
    ):
        raise ValueError("invalid base64url value")
    return decoded


def _pairing_digest(token: str) -> bytes:
    return hashlib.sha256(_b64decode(token, expected_bytes=PAIRING_TOKEN_BYTES)).digest()


def _fingerprint(public_key: bytes) -> str:
    digest = hashlib.sha256(public_key).digest()
    return "SHA256:" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _verify_jws(jws: str, public_key: bytes, *, audience: str) -> dict[str, Any]:
    if not isinstance(jws, str) or len(jws) > 8192:
        raise InvalidProof
    try:
        header = jwt.get_unverified_header(jws)
        if header.get("alg") != "EdDSA":
            raise InvalidProof
        claims = jwt.decode(
            jws,
            Ed25519PublicKey.from_public_bytes(public_key),
            algorithms=["EdDSA"],
            audience=audience,
            options={"require": ["aud", "sub"]},
        )
    except (InvalidTokenError, ValueError, TypeError) as error:
        raise InvalidProof from error
    return claims


def create_pairing(
    session_factory: SessionFactory, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> Pairing:
    raw = secrets.token_bytes(PAIRING_TOKEN_BYTES)
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with session_factory() as session, session.begin():
        now = _clock(session)
        user = session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        db_session = session.scalar(
            select(DbSession)
            .where(DbSession.id == session_id, DbSession.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            user is None
            or db_session is None
            or user.status is not AccountStatus.ACTIVE
            or user.security_version != db_session.security_version
            or db_session.revoked_at is not None
            or db_session.expires_at <= now
            or db_session.idle_expires_at <= now
        ):
            raise PairingUnavailable
        expires_at = now + PAIRING_TTL
        pairing = DevicePairingToken(
                user_id=user_id,
                initiating_session_id=session_id,
                token_digest=hashlib.sha256(raw).digest(),
                created_at=now,
                expires_at=expires_at,
            )
        session.add(pairing)
        session.flush()
        pairing_id = pairing.id
    return Pairing(id=pairing_id, token=token, expires_at=expires_at)


def revoke_pairing(
    session_factory: SessionFactory,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    pairing_id: uuid.UUID,
) -> None:
    with session_factory() as session, session.begin():
        pairing = session.scalar(
            select(DevicePairingToken)
            .where(
                DevicePairingToken.id == pairing_id,
                DevicePairingToken.user_id == user_id,
                DevicePairingToken.initiating_session_id == session_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if pairing is None:
            raise PairingNotFound
        now = _clock(session)
        if pairing.consumed_at is None and pairing.revoked_at is None and pairing.expires_at > now:
            pairing.revoked_at = now


def enroll(
    session_factory: SessionFactory,
    *,
    pairing_token: str,
    public_key_encoded: str,
    proof: str,
    name: str,
    platform: str,
    agent_version: str | None,
) -> Enrollment:
    try:
        digest = _pairing_digest(pairing_token)
        public_key = _b64decode(public_key_encoded, expected_bytes=32)
    except ValueError as error:
        raise InvalidPairing from error
    claims = _verify_jws(proof, public_key, audience=ENROLLMENT_AUDIENCE)
    claimed_pairing_token = claims.get("pairing_token")
    if not isinstance(claimed_pairing_token, str):
        raise InvalidProof
    try:
        _b64decode(claimed_pairing_token, expected_bytes=PAIRING_TOKEN_BYTES)
    except ValueError as error:
        raise InvalidProof from error
    if not hmac.compare_digest(claimed_pairing_token, pairing_token):
        raise InvalidProof
    if not isinstance(claims.get("sub"), str):
        raise InvalidProof
    with session_factory() as session, session.begin():
        pairing = session.scalar(
            select(DevicePairingToken)
            .where(DevicePairingToken.token_digest == digest)
            .with_for_update()
        )
        now = _clock(session)
        if (
            pairing is None
            or pairing.consumed_at is not None
            or pairing.revoked_at is not None
            or pairing.expires_at <= now
        ):
            raise InvalidPairing
        user = session.scalar(select(User).where(User.id == pairing.user_id).with_for_update())
        initiating = session.scalar(
            select(DbSession)
            .where(
                DbSession.id == pairing.initiating_session_id,
                DbSession.user_id == pairing.user_id,
            )
            .with_for_update()
        )
        if (
            user is None
            or initiating is None
            or user.status is not AccountStatus.ACTIVE
            or user.security_version != initiating.security_version
            or initiating.revoked_at is not None
            or initiating.expires_at <= now
            or initiating.idle_expires_at <= now
        ):
            raise InvalidPairing
        device = Device(
            id=uuid.uuid4(),
            user_id=pairing.user_id,
            name=name,
            platform=platform,
            agent_version=agent_version,
            lifecycle_status=DeviceLifecycleStatus.PENDING,
            public_key=public_key,
            public_key_fingerprint=_fingerprint(public_key),
        )
        session.add(device)
        session.flush()
        pairing.consumed_at = now
        pairing.device_id = device.id
        fingerprint = device.public_key_fingerprint
        assert fingerprint is not None
        return Enrollment(device_id=device.id, fingerprint=fingerprint)


def _owned_device(session: Session, *, user_id: uuid.UUID, device_id: uuid.UUID) -> Device:
    device = session.scalar(
        select(Device).where(Device.id == device_id, Device.user_id == user_id).with_for_update()
    )
    if device is None:
        raise DeviceNotFound
    return device


def approve(
    session_factory: SessionFactory, *, user_id: uuid.UUID, device_id: uuid.UUID, fingerprint: str
) -> None:
    with session_factory() as session, session.begin():
        device = _owned_device(session, user_id=user_id, device_id=device_id)
        if device.lifecycle_status is not DeviceLifecycleStatus.PENDING:
            raise DeviceNotPending
        if device.public_key_fingerprint is None or not hmac.compare_digest(
            device.public_key_fingerprint, fingerprint
        ):
            raise FingerprintMismatch
        device.lifecycle_status = DeviceLifecycleStatus.ACTIVE
        device.approved_at = _clock(session)


def reject(
    session_factory: SessionFactory, *, user_id: uuid.UUID, device_id: uuid.UUID, fingerprint: str
) -> None:
    with session_factory() as session, session.begin():
        device = _owned_device(session, user_id=user_id, device_id=device_id)
        if device.lifecycle_status is not DeviceLifecycleStatus.PENDING:
            raise DeviceNotPending
        if device.public_key_fingerprint is None or not hmac.compare_digest(
            device.public_key_fingerprint, fingerprint
        ):
            raise FingerprintMismatch
        device.lifecycle_status = DeviceLifecycleStatus.REVOKED


def verify_heartbeat(*, device: Device, device_id: uuid.UUID, jws: str) -> int:
    return _verify_heartbeat_claims(device=device, device_id=device_id, jws=jws)[0]


def _verify_heartbeat_claims(
    *, device: Device, device_id: uuid.UUID, jws: str
) -> tuple[int, telemetry.TelemetrySample | None]:
    if device.lifecycle_status is DeviceLifecycleStatus.REVOKED:
        raise DeviceRevoked
    if device.lifecycle_status is not DeviceLifecycleStatus.ACTIVE:
        raise DevicePending
    if device.public_key is None:
        raise InvalidProof
    claims = _verify_jws(jws, device.public_key, audience=HEARTBEAT_AUDIENCE)
    if claims.get("sub") != str(device_id):
        raise InvalidProof
    sequence = claims.get("seq")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 0 <= sequence <= MAX_SEQUENCE
    ):
        raise InvalidProof
    sample: telemetry.TelemetrySample | None = None
    if "tel" in claims:
        try:
            sample = telemetry.parse_claim(claims["tel"])
        except telemetry.InvalidTelemetry as error:
            raise InvalidProof from error
    return sequence, sample


def authenticate_heartbeat(
    session_factory: SessionFactory, *, device_id: uuid.UUID, jws: str
) -> None:
    """Validate device lifecycle and JWS before rate admission, without mutation."""
    with session_factory() as session:
        device = session.scalar(select(Device).where(Device.id == device_id))
        if device is None:
            raise DeviceNotFound
        verify_heartbeat(device=device, device_id=device_id, jws=jws)


def heartbeat(
    session_factory: SessionFactory, *, device_id: uuid.UUID, jws: str
) -> datetime:
    with session_factory() as session, session.begin():
        device = session.scalar(select(Device).where(Device.id == device_id))
        if device is None:
            raise DeviceNotFound
        sequence, sample = _verify_heartbeat_claims(device=device, device_id=device_id, jws=jws)
        accepted = session.execute(
            update(Device)
            .where(
                Device.id == device_id,
                Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE,
                Device.public_key == device.public_key,
                (Device.last_heartbeat_seq.is_(None)) | (Device.last_heartbeat_seq < sequence),
            )
            .values(last_heartbeat_seq=sequence, last_seen_at=text("clock_timestamp()"))
            .returning(Device.last_seen_at)
        ).scalar_one_or_none()
        if accepted is not None:
            if sample is not None:
                telemetry.store(session, device_id=device_id, sample=sample)
            return accepted
        current = session.scalar(select(Device.lifecycle_status).where(Device.id == device_id))
        if current is DeviceLifecycleStatus.REVOKED:
            raise DeviceRevoked
        raise StaleHeartbeat


def presence(now: datetime, device: Device) -> str:
    return (
        "online"
        if device.lifecycle_status is DeviceLifecycleStatus.ACTIVE
        and device.last_seen_at is not None
        and device.last_seen_at >= now - ONLINE_WINDOW
        else "offline"
    )
