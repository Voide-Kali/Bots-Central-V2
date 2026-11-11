"""Tests for the daily summary module."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, DeviceTelemetrySample, TelegramLink, User
from app.telegram.daily_summary import (
    DailySummarySender,
    build_summary,
)

pytestmark = pytest.mark.postgresql


def _seed_user_device(
    session: Session,
    *,
    device_name: str = "tropa",
    platform: str = "linux",
    cpu: float | None = 45.0,
    disk_used: int | None = 50_000_000_000,
    disk_total: int | None = 100_000_000_000,
    temp: float | None = 55.0,
    mem_used: int | None = 4_000_000_000,
    mem_total: int | None = 8_000_000_000,
    last_seen_ago: timedelta = timedelta(seconds=30),
) -> tuple[uuid.UUID, uuid.UUID, int]:
    """Create user, device and telegram link; return (user_id, device_id, chat_id)."""
    user_id = uuid.uuid4()
    device_id = uuid.uuid4()
    chat_id = 100_000 + (user_id.int % 100_000)

    session.add(User(id=user_id))
    session.flush()

    now = datetime.now(UTC)
    session.add(
        Device(
            id=device_id,
            user_id=user_id,
            name=device_name,
            platform=platform,
            agent_version="0.1.0",
            lifecycle_status=DeviceLifecycleStatus.ACTIVE,
            public_key=b"k" * 32,
            last_seen_at=now - last_seen_ago,
        )
    )
    session.add(
        TelegramLink(
            user_id=user_id, chat_id=chat_id, telegram_user_id=chat_id, created_at=now,
        )
    )
    session.flush()

    if cpu is not None:
        session.add(
            DeviceTelemetrySample(
                device_id=device_id,
                recorded_at=now,
                cpu_percent=cpu,
                memory_used_bytes=mem_used,
                memory_total_bytes=mem_total,
                disk_used_bytes=disk_used,
                disk_total_bytes=disk_total,
                temperature_c=temp,
            )
        )
        # Add a few more samples so 24 h aggregates are meaningful.
        for i in range(1, 4):
            session.add(
                DeviceTelemetrySample(
                    device_id=device_id,
                    recorded_at=now - timedelta(hours=i),
                    cpu_percent=cpu + i * 2,
                    disk_used_bytes=disk_used,
                    disk_total_bytes=disk_total,
                    temperature_c=(temp + i) if temp else None,
                )
            )
    session.flush()
    return user_id, device_id, chat_id


def test_build_summary_returns_none_without_devices(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id = uuid.uuid4()
        session.add(User(id=user_id))
    with factory() as session:
        assert build_summary(session, user_id) is None


def test_build_summary_includes_device_info(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id, _, _ = _seed_user_device(session, device_name="tropa", platform="linux")

    with factory() as session:
        text = build_summary(session, user_id)

    assert text is not None
    assert "RESUMO DIARIO" in text
    assert "tropa" in text
    assert "Linux" in text
    assert "1/1 online" in text
    assert "CPU" in text
    assert "Disco" in text


def test_build_summary_shows_warnings_for_high_disk(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id, _, _ = _seed_user_device(
            session,
            disk_used=95_000_000_000,
            disk_total=100_000_000_000,
        )

    with factory() as session:
        text = build_summary(session, user_id)

    assert text is not None
    assert "Atencao:" in text
    assert "disco em 95%" in text


def test_build_summary_shows_offline_warning(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id, _, _ = _seed_user_device(
            session,
            device_name="servidor",
            last_seen_ago=timedelta(minutes=10),
        )

    with factory() as session:
        text = build_summary(session, user_id)

    assert text is not None
    assert "0/1 online" in text
    assert "Atencao:" in text
    assert "servidor: offline" in text


def test_build_summary_shows_high_temp_warning(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id, _, _ = _seed_user_device(session, temp=85.0)

    with factory() as session:
        text = build_summary(session, user_id)

    assert text is not None
    assert "Atencao:" in text
    assert "temperatura 85" in text


def test_daily_sender_respects_interval(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)

    # Clean slate: remove leftover rows from previous tests.
    with factory() as session, session.begin():
        session.execute(text("DELETE FROM device_telemetry_samples"))
        session.execute(text("DELETE FROM telegram_links"))
        session.execute(text("DELETE FROM devices"))
        session.execute(text("DELETE FROM users"))

    with factory() as session, session.begin():
        _seed_user_device(session)

    fake_time = 1000.0
    sender = DailySummarySender(clock=lambda: fake_time, interval_seconds=86400)

    # First call: should produce a reply.
    replies = sender.collect(factory)
    assert len(replies) == 1
    assert "RESUMO DIARIO" in replies[0].text

    # Immediate second call: should produce nothing (within interval).
    replies = sender.collect(factory)
    assert replies == []

    # After the interval: should produce a reply again.
    fake_time = 1000.0 + 86401
    replies = sender.collect(factory)
    assert len(replies) == 1


def test_build_summary_shows_24h_aggregates(
    migrated_postgresql_engine: Engine,
) -> None:
    factory = sessionmaker(bind=migrated_postgresql_engine)
    with factory() as session, session.begin():
        user_id, _, _ = _seed_user_device(session, cpu=40.0, temp=60.0)

    with factory() as session:
        text = build_summary(session, user_id)

    assert text is not None
    assert "CPU media 24h" in text
    assert "Temp max 24h" in text
