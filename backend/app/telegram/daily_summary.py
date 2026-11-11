"""Daily summary: one message per day with the fleet overview.

Sent once per day at the configured hour (default 08:00 local).  The check runs
inside the bot loop every ``ALERT_INTERVAL_SECONDS`` (15 s) and short-circuits
after the first send: the last-sent timestamp lives in the process (like
resource-alert cooldowns), so a restart can repeat at most one summary.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import device_online
from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, DeviceTelemetrySample, TelegramLink
from app.telegram.commands import Reply
from app.telegram.formatting import friendly_platform

SessionFactory = Callable[[], Session]

# Default: send the summary once every 24 h.
SUMMARY_INTERVAL = timedelta(hours=24)

# Minimum samples in the last 24 h to show a meaningful average.
MIN_SAMPLES_FOR_AVG = 3


def _pct(used: int | None, total: int | None) -> float | None:
    if used is None or not total:
        return None
    return used * 100.0 / total


def _gb(value: int) -> str:
    return f"{value / 1024**3:.1f}".replace(".", ",")


def _bar(percent: float, width: int = 10) -> str:
    """ASCII bar: [####------] 42%."""
    filled = round(percent / 100 * width)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {percent:.0f}%"


@dataclass
class _DeviceSnapshot:
    name: str
    platform: str
    presence: str
    cpu: float | None = None
    ram_pct: float | None = None
    disk_pct: float | None = None
    disk_free_gb: str | None = None
    temp: float | None = None
    uptime_s: int | None = None
    battery_pct: int | None = None
    battery_charging: bool | None = None
    avg_cpu_24h: float | None = None
    max_temp_24h: float | None = None
    max_disk_pct_24h: float | None = None


def _device_summary_line(snap: _DeviceSnapshot) -> str:
    status = "ONLINE" if snap.presence == "online" else "OFFLINE"
    parts = [f"{snap.name} ({friendly_platform(snap.platform)}) — {status}"]

    metrics: list[str] = []
    if snap.cpu is not None:
        metrics.append(f"CPU {snap.cpu:.0f}%")
    if snap.ram_pct is not None:
        metrics.append(f"RAM {snap.ram_pct:.0f}%")
    if snap.disk_pct is not None:
        disk_str = f"Disco {_bar(snap.disk_pct)}"
        if snap.disk_free_gb is not None:
            disk_str += f" ({snap.disk_free_gb} GB livres)"
        metrics.append(disk_str)
    if snap.temp is not None:
        metrics.append(f"Temp {snap.temp:.0f} C")
    if snap.battery_pct is not None:
        charge = " (carregando)" if snap.battery_charging else ""
        metrics.append(f"Bateria {snap.battery_pct}%{charge}")
    if metrics:
        parts.append("  " + " | ".join(metrics))

    # 24 h trends when available.
    trends: list[str] = []
    if snap.avg_cpu_24h is not None:
        trends.append(f"CPU media 24h: {snap.avg_cpu_24h:.0f}%")
    if snap.max_temp_24h is not None:
        trends.append(f"Temp max 24h: {snap.max_temp_24h:.0f} C")
    if snap.max_disk_pct_24h is not None:
        trends.append(f"Disco max 24h: {snap.max_disk_pct_24h:.0f}%")
    if trends:
        parts.append("  " + " | ".join(trends))

    return "\n".join(parts)


def _collect_snapshots(
    session: Session,
    user_id: uuid.UUID,
) -> list[_DeviceSnapshot]:
    now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
    devices = session.scalars(
        select(Device)
        .where(
            Device.user_id == user_id,
            Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE,
        )
        .order_by(Device.created_at, Device.id)
    ).all()
    if not devices:
        return []

    device_ids = [d.id for d in devices]
    since = now - timedelta(hours=24)

    # Latest sample per device.
    latest_map: dict[uuid.UUID, DeviceTelemetrySample] = {}
    for did in device_ids:
        row = session.scalars(
            select(DeviceTelemetrySample)
            .where(DeviceTelemetrySample.device_id == did)
            .order_by(
                DeviceTelemetrySample.recorded_at.desc(),
                DeviceTelemetrySample.id.desc(),
            )
            .limit(1)
        ).first()
        if row is not None:
            latest_map[did] = row

    # 24 h aggregates per device.
    agg_rows = session.execute(
        select(
            DeviceTelemetrySample.device_id,
            func.avg(DeviceTelemetrySample.cpu_percent),
            func.max(DeviceTelemetrySample.temperature_c),
            func.count(DeviceTelemetrySample.id),
            func.max(
                DeviceTelemetrySample.disk_used_bytes * 100.0
                / func.nullif(DeviceTelemetrySample.disk_total_bytes, 0)
            ),
        )
        .where(
            DeviceTelemetrySample.device_id.in_(device_ids),
            DeviceTelemetrySample.recorded_at >= since,
        )
        .group_by(DeviceTelemetrySample.device_id)
    ).all()
    agg_map: dict[uuid.UUID, tuple[Any, ...]] = {}
    for agg_row in agg_rows:
        agg_map[agg_row[0]] = (agg_row[1], agg_row[2], agg_row[3], agg_row[4])

    snapshots: list[_DeviceSnapshot] = []
    for device in devices:
        presence = device_online.presence(now, device)
        latest = latest_map.get(device.id)
        agg = agg_map.get(device.id)

        snap = _DeviceSnapshot(
            name=device.name,
            platform=device.platform,
            presence=presence,
        )
        if latest is not None:
            snap.cpu = latest.cpu_percent
            snap.ram_pct = _pct(latest.memory_used_bytes, latest.memory_total_bytes)
            snap.disk_pct = _pct(latest.disk_used_bytes, latest.disk_total_bytes)
            if latest.disk_total_bytes and latest.disk_used_bytes is not None:
                free = latest.disk_total_bytes - latest.disk_used_bytes
                snap.disk_free_gb = _gb(free)
            snap.temp = latest.temperature_c
            snap.uptime_s = latest.uptime_seconds
            snap.battery_pct = latest.battery_percent
            snap.battery_charging = latest.battery_charging

        if agg is not None and agg[2] >= MIN_SAMPLES_FOR_AVG:
            snap.avg_cpu_24h = agg[0]
            snap.max_temp_24h = agg[1]
            snap.max_disk_pct_24h = agg[3]

        snapshots.append(snap)
    return snapshots


def build_summary(session: Session, user_id: uuid.UUID) -> str | None:
    """Build the daily summary text for one user, or ``None`` if no devices."""
    snapshots = _collect_snapshots(session, user_id)
    if not snapshots:
        return None

    online = sum(1 for s in snapshots if s.presence == "online")
    total = len(snapshots)
    header = f"RESUMO DIARIO — AVAL\nComputadores: {online}/{total} online"

    # Warnings section.
    warnings: list[str] = []
    for snap in snapshots:
        if snap.presence == "offline":
            warnings.append(f"  {snap.name}: offline")
        if snap.disk_pct is not None and snap.disk_pct >= 90:
            warnings.append(f"  {snap.name}: disco em {snap.disk_pct:.0f}%")
        if snap.temp is not None and snap.temp >= 80:
            warnings.append(f"  {snap.name}: temperatura {snap.temp:.0f} C")
        if snap.battery_pct is not None and snap.battery_pct <= 25 and not snap.battery_charging:
            warnings.append(f"  {snap.name}: bateria em {snap.battery_pct}%")

    lines = [header]
    if warnings:
        lines.append("")
        lines.append("Atencao:")
        lines.extend(warnings)

    lines.append("")
    for snap in snapshots:
        lines.append(_device_summary_line(snap))
        lines.append("")

    lines.append("Use /painel para detalhes ou /computadores para o estado atual.")
    return "\n".join(lines)


@dataclass
class DailySummarySender:
    """Collects and sends a daily summary once per interval.

    The ``clock`` and ``_last_sent`` fields exist for testing (inject a fake
    clock and verify the send cadence without waiting 24 h).
    """

    clock: Callable[[], float] = time.monotonic
    _last_sent: dict[uuid.UUID, float] = field(default_factory=dict)
    interval_seconds: float = SUMMARY_INTERVAL.total_seconds()

    def collect(self, session_factory: SessionFactory) -> list[Reply]:
        replies: list[Reply] = []
        now = self.clock()
        with session_factory() as session:
            rows = session.execute(
                select(TelegramLink.user_id, TelegramLink.chat_id)
            ).all()
            for user_id, chat_id in rows:
                last = self._last_sent.get(user_id)
                if last is not None and now - last < self.interval_seconds:
                    continue
                text = build_summary(session, user_id)
                if text is not None:
                    replies.append(Reply(chat_id, text))
                self._last_sent[user_id] = now
        return replies
