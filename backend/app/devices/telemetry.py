"""Bounded system telemetry carried inside the signed heartbeat JWS (ADR-012).

The optional ``tel`` claim is authenticated by the device key and replay-protected by
the heartbeat sequence. Validation is strict: unknown keys, wrong types, and
out-of-range values reject the whole heartbeat rather than storing guesses.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.db.models import Device, DeviceTelemetrySample

TELEMETRY_VERSION = 1
RETENTION = timedelta(days=7)
MAX_HISTORY_MINUTES = 24 * 60
MAX_HISTORY_ROWS = 3000
_MAX_BIGINT = (1 << 63) - 1
_ALLOWED_KEYS = frozenset(
    {
        "v",
        "cpu_pct",
        "load1",
        "cpus",
        "mem_total",
        "mem_used",
        "disk_total",
        "disk_used",
        "temp_c",
        "uptime_s",
    }
)


class InvalidTelemetry(Exception):
    pass


@dataclass(frozen=True)
class TelemetrySample:
    cpu_percent: float | None = None
    load1: float | None = None
    cpu_count: int | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    temperature_c: float | None = None
    uptime_seconds: int | None = None


def _float(claim: dict[str, Any], key: str, low: float, high: float) -> float | None:
    value = claim.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidTelemetry
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise InvalidTelemetry
    return number


def _int(claim: dict[str, Any], key: str, low: int, high: int) -> int | None:
    value = claim.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidTelemetry
    return int(value)


def _pair(total: int | None, used: int | None) -> None:
    if (total is None) != (used is None):
        raise InvalidTelemetry
    if total is not None and used is not None and used > total:
        raise InvalidTelemetry


def parse_claim(value: object) -> TelemetrySample:
    if not isinstance(value, dict) or not set(value) <= _ALLOWED_KEYS:
        raise InvalidTelemetry
    version = value.get("v")
    if isinstance(version, bool) or version != TELEMETRY_VERSION:
        raise InvalidTelemetry
    sample = TelemetrySample(
        cpu_percent=_float(value, "cpu_pct", 0.0, 100.0),
        load1=_float(value, "load1", 0.0, 1_000_000.0),
        cpu_count=_int(value, "cpus", 1, 65_536),
        memory_total_bytes=_int(value, "mem_total", 0, _MAX_BIGINT),
        memory_used_bytes=_int(value, "mem_used", 0, _MAX_BIGINT),
        disk_total_bytes=_int(value, "disk_total", 0, _MAX_BIGINT),
        disk_used_bytes=_int(value, "disk_used", 0, _MAX_BIGINT),
        temperature_c=_float(value, "temp_c", -50.0, 150.0),
        uptime_seconds=_int(value, "uptime_s", 0, _MAX_BIGINT),
    )
    _pair(sample.memory_total_bytes, sample.memory_used_bytes)
    _pair(sample.disk_total_bytes, sample.disk_used_bytes)
    return sample


def store(session: Session, *, device_id: uuid.UUID, sample: TelemetrySample) -> None:
    """Insert inside the caller's heartbeat transaction and prune this device's old rows."""
    now = session.scalar(text("SELECT clock_timestamp()"))
    session.add(
        DeviceTelemetrySample(
            device_id=device_id,
            recorded_at=now,
            cpu_percent=sample.cpu_percent,
            load1=sample.load1,
            cpu_count=sample.cpu_count,
            memory_total_bytes=sample.memory_total_bytes,
            memory_used_bytes=sample.memory_used_bytes,
            disk_total_bytes=sample.disk_total_bytes,
            disk_used_bytes=sample.disk_used_bytes,
            temperature_c=sample.temperature_c,
            uptime_seconds=sample.uptime_seconds,
        )
    )
    session.execute(
        delete(DeviceTelemetrySample).where(
            DeviceTelemetrySample.device_id == device_id,
            DeviceTelemetrySample.recorded_at < now - RETENTION,
        )
    )


def to_json(row: DeviceTelemetrySample) -> dict[str, Any]:
    return {
        "recorded_at": row.recorded_at.isoformat(),
        "cpu_percent": row.cpu_percent,
        "load1": row.load1,
        "cpu_count": row.cpu_count,
        "memory_total_bytes": row.memory_total_bytes,
        "memory_used_bytes": row.memory_used_bytes,
        "disk_total_bytes": row.disk_total_bytes,
        "disk_used_bytes": row.disk_used_bytes,
        "temperature_c": row.temperature_c,
        "uptime_seconds": row.uptime_seconds,
    }


def latest_for_devices(
    session: Session, device_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DeviceTelemetrySample]:
    if not device_ids:
        return {}
    rows = session.scalars(
        select(DeviceTelemetrySample)
        .where(DeviceTelemetrySample.device_id.in_(device_ids))
        .order_by(
            DeviceTelemetrySample.device_id,
            DeviceTelemetrySample.recorded_at.desc(),
            DeviceTelemetrySample.id.desc(),
        )
        .distinct(DeviceTelemetrySample.device_id)
    ).all()
    return {row.device_id: row for row in rows}


class DeviceNotOwned(Exception):
    pass


def history(
    session: Session, *, user_id: uuid.UUID, device_id: uuid.UUID, minutes: int
) -> list[DeviceTelemetrySample]:
    if not 1 <= minutes <= MAX_HISTORY_MINUTES:
        raise ValueError("minutes out of range")
    owned = session.scalar(
        select(Device.id).where(Device.id == device_id, Device.user_id == user_id)
    )
    if owned is None:
        raise DeviceNotOwned
    since: datetime = session.scalar(text("SELECT clock_timestamp()")) - timedelta(
        minutes=minutes
    )
    rows = session.scalars(
        select(DeviceTelemetrySample)
        .where(
            DeviceTelemetrySample.device_id == device_id,
            DeviceTelemetrySample.recorded_at >= since,
        )
        .order_by(DeviceTelemetrySample.recorded_at.desc(), DeviceTelemetrySample.id.desc())
        .limit(MAX_HISTORY_ROWS)
    ).all()
    return list(reversed(rows))
