"""Events a computer reports by itself (ADR-019): a wrong password, with a photo.

The agent signs the event (own audience, shared anti-replay sequence) and sends the photo
next to it; its size and SHA-256 are inside the signed claims. Nothing here can make the
agent do anything: the data only flows from the computer to its owner's Telegram.
"""

import base64
import hashlib
import hmac
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.core.timezone import local
from app.db.models import Device, DeviceEvent, TelegramLink
from app.devices.commands import _verify_signed

SessionFactory = Callable[[], Session]

EVENT_AUDIENCE = "bots-central:event:v1"
KINDS = frozenset({"failed_login"})
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TTL = timedelta(hours=24)
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9_.@-]{0,63}$")

# What the owner reads for each program that reported the wrong password.
SOURCES = {
    "gdm-password": "tela de login",
    "gdm-autologin": "tela de login",
    "lightdm": "tela de login",
    "sddm": "tela de login",
    "gnome-screensaver": "tela de bloqueio",
    "xfce4-screensaver": "tela de bloqueio",
    "kscreenlocker": "tela de bloqueio",
    "cinnamon-screensaver": "tela de bloqueio",
    "login": "login no terminal",
    "sudo": "sudo",
    "su": "su",
    "sshd": "acesso remoto (SSH)",
    "polkit-agent-helper-1": "pedido de senha do sistema",
}


class InvalidEvent(Exception):
    pass


def record_event(
    session_factory: SessionFactory,
    *,
    device_id: uuid.UUID,
    jws: str,
    photo_b64: str | None,
) -> uuid.UUID:
    with session_factory() as session, session.begin():
        device, claims = _verify_signed(
            session, device_id=device_id, jws=jws, audience=EVENT_AUDIENCE
        )
        kind = claims.get("kind")
        source = claims.get("source")
        if kind not in KINDS or not isinstance(source, str) or not _SOURCE.match(source):
            raise InvalidEvent
        photo: bytes | None = None
        size, digest_text = claims.get("size"), claims.get("sha256")
        if photo_b64 is not None:
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 0 < size <= MAX_PHOTO_BYTES
                or not isinstance(digest_text, str)
            ):
                raise InvalidEvent
            try:
                photo = base64.b64decode(photo_b64, validate=True)
                signed = bytes.fromhex(digest_text)
            except ValueError as error:
                raise InvalidEvent from error
            if (
                len(photo) != size
                or len(signed) != 32
                or not hmac.compare_digest(hashlib.sha256(photo).digest(), signed)
            ):
                raise InvalidEvent
        elif size is not None or digest_text is not None:
            raise InvalidEvent
        now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
        event = DeviceEvent(
            user_id=device.user_id,
            device_id=device.id,
            kind=cast(str, kind),
            source=source,
            photo=photo,
            created_at=now,
        )
        session.add(event)
        session.flush()
        audit.record(
            session,
            user_id=device.user_id,
            action="sensor.failed_login",
            actor="device",
            target_type="device",
            target_id=str(device.id),
            outcome="denied",
            details={"name": device.name, "source": source, "photo": photo is not None},
        )
        return event.id


@dataclass(frozen=True)
class EventDelivery:
    event_id: uuid.UUID
    chat_id: int
    caption: str
    photo: bytes | None


def caption(device_name: str, source: str, at: datetime) -> str:
    where = SOURCES.get(source, source)
    return f"Senha errada no {device_name} ({where}), {local(at):%d/%m %H:%M}."


def pending_events(session_factory: SessionFactory) -> list[EventDelivery]:
    """Events still to send to a linked owner. Old photos are dropped first."""
    with session_factory() as session, session.begin():
        now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
        session.execute(
            update(DeviceEvent)
            .where(DeviceEvent.photo.is_not(None), DeviceEvent.created_at <= now - PHOTO_TTL)
            .values(photo=None)
        )
        rows = session.execute(
            select(DeviceEvent, Device.name, TelegramLink.chat_id)
            .join(Device, Device.id == DeviceEvent.device_id)
            .join(TelegramLink, TelegramLink.user_id == DeviceEvent.user_id)
            .where(DeviceEvent.delivered_at.is_(None), DeviceEvent.created_at > now - PHOTO_TTL)
            .order_by(DeviceEvent.created_at)
            .limit(20)
        ).all()
        return [
            EventDelivery(
                event_id=event.id,
                chat_id=chat_id,
                caption=caption(name, event.source, event.created_at),
                photo=event.photo,
            )
            for event, name, chat_id in rows
        ]


def mark_delivered(session_factory: SessionFactory, *, event_id: uuid.UUID) -> None:
    """The photo leaves the database as soon as the owner has it."""
    with session_factory() as session, session.begin():
        session.execute(
            update(DeviceEvent)
            .where(DeviceEvent.id == event_id)
            .values(delivered_at=text("clock_timestamp()"), photo=None)
        )
        session.execute(
            delete(DeviceEvent).where(
                DeviceEvent.delivered_at.is_not(None),
                DeviceEvent.delivered_at <= text("clock_timestamp() - interval '30 days'"),
            )
        )
