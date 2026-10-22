"""Queries behind the admin tab. Nothing here returns file bytes, photos, PINs,
password hashes or other users' detailed telemetry (ADR-017)."""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.auth import device_online
from app.db.enums import AccountStatus
from app.db.models import (
    ActionPin,
    AuditEvent,
    Device,
    DeviceCommand,
    TelegramLink,
    User,
    UserEmail,
)

SessionFactory = Callable[[], Session]


class NotFound(Exception):
    pass


def _now(session: Session) -> datetime:
    return cast(datetime, session.scalar(text("SELECT clock_timestamp()")))


def overview(session: Session) -> dict[str, Any]:
    now = _now(session)
    users = dict(
        session.execute(select(User.status, func.count()).group_by(User.status)).tuples().all()
    )
    devices = session.scalars(select(Device)).all()
    lifecycle: dict[str, int] = {}
    online = 0
    for device in devices:
        lifecycle[device.lifecycle_status.value] = (
            lifecycle.get(device.lifecycle_status.value, 0) + 1
        )
        if (
            device.lifecycle_status.value == "active"
            and device_online.presence(now, device) == "online"
        ):
            online += 1
    commands = dict(
        session.execute(
            select(DeviceCommand.status, func.count())
            .where(DeviceCommand.created_at >= now - timedelta(days=1))
            .group_by(DeviceCommand.status)
        )
        .tuples()
        .all()
    )
    return {
        "checked_at": now.isoformat(),
        "users": {status.value: count for status, count in users.items()},
        "devices": {"by_lifecycle": lifecycle, "online": online},
        "commands_24h": commands,
        "telegram_links": session.scalar(select(func.count()).select_from(TelegramLink)) or 0,
    }


def list_users(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(User, UserEmail.email_display)
        .join(UserEmail, (UserEmail.user_id == User.id) & UserEmail.is_primary.is_(True))
        .order_by(User.created_at.desc())
        .limit(200)
    ).all()
    device_counts = dict(
        session.execute(select(Device.user_id, func.count()).group_by(Device.user_id))
        .tuples()
        .all()
    )
    linked = set(session.scalars(select(TelegramLink.user_id)).all())
    pins = set(session.scalars(select(ActionPin.user_id)).all())
    return [
        {
            "id": str(user.id),
            "email": email,
            "status": user.status.value,
            "role": user.role,
            "created_at": user.created_at.isoformat(),
            "devices": device_counts.get(user.id, 0),
            "telegram": user.id in linked,
            "pin": user.id in pins,
        }
        for user, email in rows
    ]


def activate_user(
    session_factory: SessionFactory, *, admin_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Admin repair: mark a pending account's primary e-mail as verified and activate it."""
    with session_factory() as session, session.begin():
        user = session.get(User, user_id, with_for_update=True)
        if user is None:
            raise NotFound
        if user.status is not AccountStatus.PENDING_VERIFICATION:
            return
        now = _now(session)
        email = session.scalar(
            select(UserEmail).where(UserEmail.user_id == user_id, UserEmail.is_primary.is_(True))
        )
        if email is None:
            raise NotFound
        email.verified_at = now
        user.status = AccountStatus.ACTIVE
        for target, actor in ((admin_id, "user"), (user_id, "system")):
            audit.record(
                session,
                user_id=target,
                action="admin.user_activated",
                actor=actor,  # type: ignore[arg-type]
                target_type="user",
                target_id=str(user_id),
            )


def recent_failures(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(DeviceCommand, Device.name, UserEmail.email_display)
        .join(Device, Device.id == DeviceCommand.device_id)
        .join(
            UserEmail,
            (UserEmail.user_id == DeviceCommand.user_id) & UserEmail.is_primary.is_(True),
        )
        .where(DeviceCommand.status.in_(("failed", "denied", "expired")))
        .order_by(DeviceCommand.created_at.desc())
        .limit(50)
    ).all()
    return [
        {
            "at": command.created_at.isoformat(),
            "user": email,
            "device": device_name,
            "action": command.kind,
            "status": command.status,
            "error": command.error_code,
        }
        for command, device_name, email in rows
    ]


def recent_audit(session: Session, limit: int = 100) -> list[dict[str, Any]]:
    rows = session.execute(
        select(AuditEvent, UserEmail.email_display)
        .outerjoin(
            UserEmail,
            (UserEmail.user_id == AuditEvent.user_id) & UserEmail.is_primary.is_(True),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
    result = []
    for event, email in rows:
        item = audit.to_json(event)
        item["user"] = email
        item["details"] = {
            k: v for k, v in (event.details or {}).items() if k in ("name", "action")
        }
        result.append(item)
    return result


def set_role(session_factory: SessionFactory, *, email: str, role: str) -> bool:
    if role not in ("user", "admin"):
        raise ValueError("role")
    with session_factory() as session, session.begin():
        user_id = session.scalar(
            select(UserEmail.user_id).where(UserEmail.email_canonical == email.strip().lower())
        )
        if user_id is None:
            return False
        user = session.get(User, user_id, with_for_update=True)
        assert user is not None
        user.role = role
        audit.record(
            session,
            user_id=user_id,
            action="admin.role_changed",
            actor="system",
            target_type="user",
            target_id=str(user_id),
            details={"role": role},
        )
        return True
