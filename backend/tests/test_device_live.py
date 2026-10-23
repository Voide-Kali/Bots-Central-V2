"""ADR-018: live telemetry while the owner watches."""

# ruff: noqa: F811
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from test_device_telemetry import VALID, _active_device, _beat, _count, pg_cleanup  # noqa: F401

from app.auth import device_online


def _live(private: Ed25519PrivateKey, device_id: uuid.UUID, seq: int, tel: object = VALID) -> str:
    claims: dict[str, object] = {
        "aud": device_online.LIVE_AUDIENCE,
        "sub": str(device_id),
        "seq": seq,
        "tel": tel,
    }
    return jwt.encode(claims, private, algorithm="EdDSA")


@pytest.mark.postgresql
@pytest.mark.usefixtures("pg_cleanup")
def test_live_samples_are_stored_only_while_the_owner_watches(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    user_id, device_id, private = _active_device(factory)
    # Nobody watching: the agent is told to stay calm and nothing is stored.
    calm = device_online.live(factory, device_id=device_id, jws=_live(private, device_id, 1))
    assert calm is False
    assert _count(factory, device_id) == 0
    device_online.watch(factory, user_id=user_id, device_id=device_id)
    for seq in (2, 3, 4):
        assert device_online.live(factory, device_id=device_id, jws=_live(private, device_id, seq))
    assert _count(factory, device_id) == 3
    # The live route shares the heartbeat sequence: replays are refused.
    with pytest.raises(device_online.StaleHeartbeat):
        device_online.live(factory, device_id=device_id, jws=_live(private, device_id, 3))
    with pytest.raises(device_online.StaleHeartbeat):
        device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, 4))


@pytest.mark.postgresql
@pytest.mark.usefixtures("pg_cleanup")
def test_live_needs_its_own_audience_and_only_the_owner_can_watch(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    user_id, device_id, private = _active_device(factory)
    with pytest.raises(device_online.InvalidProof):
        # A heartbeat token cannot be replayed on the live route.
        device_online.live(factory, device_id=device_id, jws=_beat(private, device_id, 1, VALID))
    with pytest.raises(device_online.DeviceNotFound):
        device_online.watch(factory, user_id=uuid.uuid4(), device_id=device_id)
    other_user, other_device, _ = _active_device(factory)
    assert other_user != user_id
    with pytest.raises(device_online.DeviceNotFound):
        device_online.watch(factory, user_id=user_id, device_id=other_device)
