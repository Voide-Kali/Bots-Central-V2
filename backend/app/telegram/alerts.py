"""Presence-change alerts: announce online/offline transitions once each."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import device_online
from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, DevicePresenceAlert, TelegramLink
from app.telegram.commands import Reply

SessionFactory = Callable[[], Session]

# A computer counts as offline after 90 s, but the owner is warned only after it has been
# silent for 3 minutes, so one or two lost heartbeats do not send "offline/online" pairs.
OFFLINE_ALERT_AFTER = timedelta(minutes=3)


def collect_presence_alerts(session_factory: SessionFactory) -> list[Reply]:
    """Return alerts for active devices of linked users whose presence changed.

    The first observation of a device is recorded silently. State is committed
    before messages are returned, so a crash may drop an alert but never repeats one.
    """
    replies: list[Reply] = []
    with session_factory() as session, session.begin():
        now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
        rows = session.execute(
            select(Device, TelegramLink.chat_id)
            .join(TelegramLink, TelegramLink.user_id == Device.user_id)
            .where(Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE)
        ).all()
        for device, chat_id in rows:
            presence = device_online.presence(now, device)
            state = session.scalar(
                select(DevicePresenceAlert)
                .where(DevicePresenceAlert.device_id == device.id)
                .with_for_update()
            )
            if state is None:
                session.add(
                    DevicePresenceAlert(device_id=device.id, last_presence=presence, updated_at=now)
                )
                continue
            if state.last_presence == presence:
                continue
            if (
                presence == "offline"
                and device.last_seen_at is not None
                and now - device.last_seen_at < OFFLINE_ALERT_AFTER
            ):
                continue  # maybe a lost heartbeat: decide on a later pass
            state.last_presence = presence
            state.updated_at = now
            if presence == "offline":
                replies.append(Reply(chat_id, f"{device.name} ficou offline."))
            else:
                replies.append(Reply(chat_id, f"{device.name} voltou a ficar online."))
    return replies
