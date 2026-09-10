"""Real PostgreSQL contract tests for Device Online V0.1."""

import base64
import hashlib
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.auth import device_online
from app.db.enums import AccountStatus, AuthenticationLevel, DeviceLifecycleStatus
from app.db.models import Device, DevicePairingToken, User
from app.db.models import Session as DbSession

pytestmark = pytest.mark.postgresql

_CREATED_USER_IDS: set[uuid.UUID] = set()


@pytest.fixture(autouse=True)
def cleanup_device_online_rows(migrated_postgresql_engine: Engine) -> Generator[None, None, None]:
    """These concurrency tests commit; remove only their rows after every test."""
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


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


def _identity(factory: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    _CREATED_USER_IDS.add(user_id)
    session_id = uuid.uuid4()
    user = User(id=user_id, status=AccountStatus.ACTIVE, security_version=0)
    db_session = DbSession(
        id=session_id,
        user_id=user_id,
        last_seen_at=now,
        expires_at=now + timedelta(days=1),
        idle_expires_at=now + timedelta(hours=1),
        security_version=0,
        authentication_level=AuthenticationLevel.PASSWORD_AUTHENTICATED,
        authentication_methods=["test"],
    )
    with factory() as session, session.begin():
        session.add(user)
        session.flush()
        session.add(db_session)
    return user_id, session_id


def _key_material() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, base64.urlsafe_b64encode(public).decode("ascii").rstrip("=")


def _enroll(
    factory: sessionmaker[Session], *, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[uuid.UUID, str, Ed25519PrivateKey, str]:
    pairing = device_online.create_pairing(factory, user_id=user_id, session_id=session_id)
    private, public_key = _key_material()
    proof = jwt.encode(
        {
            "aud": device_online.ENROLLMENT_AUDIENCE,
            "sub": "enrollment",
            "pairing_token": pairing.token,
        },
        private,
        algorithm="EdDSA",
    )
    enrolled = device_online.enroll(
        factory,
        pairing_token=pairing.token,
        public_key_encoded=public_key,
        proof=proof,
        name="test-agent",
        platform="linux",
        agent_version="0.1",
    )
    return enrolled.device_id, enrolled.fingerprint, private, pairing.token


def _heartbeat(private: Ed25519PrivateKey, device_id: uuid.UUID, sequence: int) -> str:
    return jwt.encode(
        {"aud": device_online.HEARTBEAT_AUDIENCE, "sub": str(device_id), "seq": sequence},
        private,
        algorithm="EdDSA",
    )


def test_pairing_persists_only_digest_and_enrollment_is_one_time(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = _factory(migrated_postgresql_engine)
    user_id, session_id = _identity(factory)
    device_id, fingerprint, _, pairing_token = _enroll(
        factory, user_id=user_id, session_id=session_id
    )
    with factory() as session:
        pairing = session.scalar(
            select(DevicePairingToken).where(DevicePairingToken.device_id == device_id)
        )
        device = session.get(Device, device_id)
        assert pairing is not None and device is not None
        assert pairing.token_digest == hashlib.sha256(
            base64.urlsafe_b64decode(pairing_token + "=")
        ).digest()
        assert pairing_token.encode() not in pairing.token_digest
        assert device.lifecycle_status is DeviceLifecycleStatus.PENDING
        assert device.public_key_fingerprint == fingerprint
    second_private, second_public = _key_material()
    second_proof = jwt.encode(
        {
            "aud": device_online.ENROLLMENT_AUDIENCE,
            "sub": "enrollment",
            "pairing_token": pairing_token,
        },
        second_private,
        algorithm="EdDSA",
    )
    with pytest.raises(device_online.InvalidPairing):
        device_online.enroll(
            factory,
            pairing_token=pairing_token,
            public_key_encoded=second_public,
            proof=second_proof,
            name="again",
            platform="linux",
            agent_version=None,
        )


def test_pending_approval_and_heartbeat_replay_are_server_authoritative(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = _factory(migrated_postgresql_engine)
    user_id, session_id = _identity(factory)
    device_id, fingerprint, private, _ = _enroll(factory, user_id=user_id, session_id=session_id)
    signed = _heartbeat(private, device_id, 1)
    with pytest.raises(device_online.DevicePending):
        device_online.heartbeat(factory, device_id=device_id, jws=signed)
    device_online.approve(factory, user_id=user_id, device_id=device_id, fingerprint=fingerprint)
    accepted_at = device_online.heartbeat(factory, device_id=device_id, jws=signed)
    with factory() as session:
        device = session.get(Device, device_id)
        assert device is not None
        assert device.last_seen_at == accepted_at
        assert device_online.presence(accepted_at, device) == "online"
    with pytest.raises(device_online.StaleHeartbeat):
        device_online.heartbeat(factory, device_id=device_id, jws=signed)


def test_same_sequence_is_accepted_once_under_concurrency(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = _factory(migrated_postgresql_engine)
    user_id, session_id = _identity(factory)
    device_id, fingerprint, private, _ = _enroll(factory, user_id=user_id, session_id=session_id)
    device_online.approve(factory, user_id=user_id, device_id=device_id, fingerprint=fingerprint)
    signed = _heartbeat(private, device_id, 9)

    def submit() -> str:
        try:
            device_online.heartbeat(factory, device_id=device_id, jws=signed)
            return "accepted"
        except device_online.StaleHeartbeat:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: submit(), range(2)))
    assert outcomes == ["accepted", "stale"]


def test_revoked_device_cannot_heartbeat(migrated_postgresql_engine: Engine) -> None:
    factory = _factory(migrated_postgresql_engine)
    user_id, session_id = _identity(factory)
    device_id, fingerprint, private, _ = _enroll(factory, user_id=user_id, session_id=session_id)
    device_online.reject(factory, user_id=user_id, device_id=device_id, fingerprint=fingerprint)
    with pytest.raises(device_online.DeviceRevoked):
        device_online.heartbeat(factory, device_id=device_id, jws=_heartbeat(private, device_id, 1))


def test_public_key_fingerprint_is_immutable_after_enrollment(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = _factory(migrated_postgresql_engine)
    user_id, session_id = _identity(factory)
    device_id, _, _, _ = _enroll(factory, user_id=user_id, session_id=session_id)
    with pytest.raises(SQLAlchemyError):
        with factory() as session, session.begin():
            device = session.get(Device, device_id)
            assert device is not None
            device.public_key_fingerprint = "SHA256:" + "z" * 43
