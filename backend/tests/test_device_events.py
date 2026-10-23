"""ADR-019: wrong-password events with a photo, delivered only to the owner."""

# ruff: noqa: F811
import base64
import hashlib
import uuid
from collections.abc import Generator
from datetime import timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import _active_device, pg_cleanup  # noqa: F401
from test_telegram import CHAT, _link

from app.auth import device_online
from app.db.models import DeviceEvent, TelegramLink
from app.devices import events

PHOTO = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


@pytest.fixture
def factory(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[sessionmaker[Session], None, None]:
    request.getfixturevalue("pg_cleanup")
    made = sessionmaker(bind=migrated_postgresql_engine)
    yield made
    with made() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id == CHAT))


def _event(private: Ed25519PrivateKey, device_id: uuid.UUID, seq: int, **claims: Any) -> str:
    body: dict[str, Any] = {
        "aud": events.EVENT_AUDIENCE,
        "sub": str(device_id),
        "seq": seq,
        "kind": "failed_login",
        "source": "gdm-password",
        **claims,
    }
    return jwt.encode(body, private, algorithm="EdDSA")


def _photo_claims(content: bytes = PHOTO) -> dict[str, Any]:
    return {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


@pytest.mark.postgresql
def test_event_with_photo_goes_to_the_owner_once(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    events.record_event(
        factory,
        device_id=device_id,
        jws=_event(private, device_id, 1, **_photo_claims()),
        photo_b64=base64.b64encode(PHOTO).decode(),
    )
    pending = [item for item in events.pending_events(factory) if item.chat_id == CHAT]
    assert len(pending) == 1 and pending[0].photo == PHOTO
    assert pending[0].caption.startswith("Senha errada no telemetry-agent (tela de login), ")
    events.mark_delivered(factory, event_id=pending[0].event_id)
    assert [item for item in events.pending_events(factory) if item.chat_id == CHAT] == []
    with factory() as session:  # the photo left the database with the delivery
        stored = session.scalar(select(DeviceEvent).where(DeviceEvent.device_id == device_id))
        assert stored is not None and stored.photo is None and stored.delivered_at is not None


@pytest.mark.postgresql
def test_event_without_photo_and_bad_events_are_refused(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    events.record_event(
        factory, device_id=device_id, jws=_event(private, device_id, 1), photo_b64=None
    )
    good = base64.b64encode(PHOTO).decode()
    with pytest.raises(events.InvalidEvent):  # bytes do not match the signed hash
        events.record_event(
            factory,
            device_id=device_id,
            jws=_event(private, device_id, 2, **_photo_claims(b"other")),
            photo_b64=good,
        )
    with pytest.raises(events.InvalidEvent):  # unknown kind
        events.record_event(
            factory,
            device_id=device_id,
            jws=_event(private, device_id, 3, kind="x"),
            photo_b64=None,
        )
    with pytest.raises(events.InvalidEvent):  # free text is not a program name
        events.record_event(
            factory,
            device_id=device_id,
            jws=_event(private, device_id, 4, source="Falha: senha 1234"),
            photo_b64=None,
        )
    with pytest.raises(device_online.StaleHeartbeat):  # same anti-replay sequence
        events.record_event(
            factory, device_id=device_id, jws=_event(private, device_id, 1), photo_b64=None
        )
    with pytest.raises(device_online.InvalidProof):  # a heartbeat token is not an event
        token = jwt.encode(
            {"aud": device_online.HEARTBEAT_AUDIENCE, "sub": str(device_id), "seq": 9},
            private,
            algorithm="EdDSA",
        )
        events.record_event(factory, device_id=device_id, jws=token, photo_b64=None)
    pending = [item for item in events.pending_events(factory) if item.chat_id == CHAT]
    assert len(pending) == 1 and pending[0].photo is None


@pytest.mark.postgresql
def test_old_photos_are_dropped_after_a_day(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    events.record_event(
        factory,
        device_id=device_id,
        jws=_event(private, device_id, 1, **_photo_claims()),
        photo_b64=base64.b64encode(PHOTO).decode(),
    )
    with factory() as session, session.begin():
        session.execute(
            update(DeviceEvent)
            .where(DeviceEvent.device_id == device_id)
            .values(created_at=DeviceEvent.created_at - timedelta(hours=25))
        )
    assert [item for item in events.pending_events(factory) if item.chat_id == CHAT] == []
    with factory() as session:
        stored = session.scalar(select(DeviceEvent).where(DeviceEvent.device_id == device_id))
        assert stored is not None and stored.photo is None
