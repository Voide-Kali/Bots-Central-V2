"""Presence-change alerts: announce online/offline transitions once each.

Also a low-battery alert, edge-triggered the same way (see ``LOW_BATTERY_PERCENT``).
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import device_online
from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, DevicePresenceAlert, DeviceTelemetrySample, TelegramLink
from app.telegram.commands import Reply

SessionFactory = Callable[[], Session]

# A computer counts as offline after 90 s, but the owner is warned only after it has been
# silent for 3 minutes, so one or two lost heartbeats do not send "offline/online" pairs.
OFFLINE_ALERT_AFTER = timedelta(minutes=3)

# A battery at or below this level, while not charging, warns the owner once. Like the
# presence alerts this is edge-triggered: it fires when a device enters the
# low-and-discharging state and stays quiet until it recovers (charges or rises above the
# level) and drops again. The "already warned" flag lives in the bot process like the
# resource-alert cooldowns: a restart may repeat one warning, never hide one.
LOW_BATTERY_PERCENT = 25

# device_id -> whether the device was low-and-discharging on the last pass. Persists across
# the bot loop's passes; tests pass their own dict to collect_presence_alerts to isolate.
_LOW_BATTERY_SEEN: dict[uuid.UUID, bool] = {}


def _battery_low(sample: DeviceTelemetrySample | None) -> bool:
    return (
        sample is not None
        and sample.battery_percent is not None
        and sample.battery_percent <= LOW_BATTERY_PERCENT
        and not sample.battery_charging
    )


def _latest_battery(session: Session, device_id: uuid.UUID) -> DeviceTelemetrySample | None:
    return session.scalars(
        select(DeviceTelemetrySample)
        .where(DeviceTelemetrySample.device_id == device_id)
        .order_by(DeviceTelemetrySample.recorded_at.desc(), DeviceTelemetrySample.id.desc())
        .limit(1)
    ).first()


def collect_presence_alerts(
    session_factory: SessionFactory,
    *,
    battery_state: dict[uuid.UUID, bool] | None = None,
) -> list[Reply]:
    """Return alerts for active devices of linked users whose presence changed.

    The first observation of a device is recorded silently. State is committed
    before messages are returned, so a crash may drop an alert but never repeats one.
    A low-and-discharging battery is also reported once per episode (``battery_state``).
    """
    if battery_state is None:
        battery_state = _LOW_BATTERY_SEEN
    replies: list[Reply] = []
    with session_factory() as session, session.begin():
        now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
        rows = session.execute(
            select(Device, TelegramLink.chat_id)
            .join(TelegramLink, TelegramLink.user_id == Device.user_id)
            .where(Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE)
        ).all()
        for device, chat_id in rows:
            latest = _latest_battery(session, device.id)
            low = _battery_low(latest)
            if low and not battery_state.get(device.id, False):
                percent = cast(int, cast(DeviceTelemetrySample, latest).battery_percent)
                replies.append(Reply(chat_id, f"Bateria do {device.name} em {percent}%."))
            battery_state[device.id] = low
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
