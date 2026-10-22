"""Low-battery alert: fires once per low-and-discharging episode, owner-only (read-only)."""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_device_telemetry import VALID, _active_device, _beat, pg_cleanup  # noqa: F401
from test_telegram import CHAT, _link

from app.auth import device_online
from app.db.models import TelegramLink
from app.telegram.alerts import collect_presence_alerts


@pytest.fixture
def factory(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[sessionmaker[Session], None, None]:
    request.getfixturevalue("pg_cleanup")
    made = sessionmaker(bind=migrated_postgresql_engine)
    yield made
    with made() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id == CHAT))


def _battery(
    factory: sessionmaker[Session], device_id: uuid.UUID, private: Any, seq: int, **changes: Any
) -> None:
    tel = {**VALID, **changes}
    device_online.heartbeat(factory, device_id=device_id, jws=_beat(private, device_id, seq, tel))


@pytest.mark.postgresql
def test_low_battery_alerts_once_per_episode(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    state: dict[uuid.UUID, bool] = {}

    def mine() -> list[str]:
        replies = collect_presence_alerts(factory, battery_state=state)
        return [r.text for r in replies if r.chat_id == CHAT]

    _battery(factory, device_id, private, 1, battery_pct=18, battery_charging=False)
    assert any("Bateria do" in text and "18%" in text for text in mine())
    assert mine() == []  # still low on later passes: no repeat
    _battery(factory, device_id, private, 2, battery_pct=15, battery_charging=False)
    assert mine() == []


@pytest.mark.postgresql
def test_low_but_charging_does_not_alert(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    state: dict[uuid.UUID, bool] = {}
    _battery(factory, device_id, private, 1, battery_pct=10, battery_charging=True)
    replies = collect_presence_alerts(factory, battery_state=state)
    assert [r.text for r in replies if r.chat_id == CHAT] == []


@pytest.mark.postgresql
def test_healthy_battery_does_not_alert(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    state: dict[uuid.UUID, bool] = {}
    _battery(factory, device_id, private, 1, battery_pct=80, battery_charging=False)
    replies = collect_presence_alerts(factory, battery_state=state)
    assert [r.text for r in replies if r.chat_id == CHAT] == []


@pytest.mark.postgresql
def test_alerts_again_after_recovery(factory: sessionmaker[Session]) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    state: dict[uuid.UUID, bool] = {}

    def mine() -> list[str]:
        replies = collect_presence_alerts(factory, battery_state=state)
        return [r.text for r in replies if r.chat_id == CHAT]

    _battery(factory, device_id, private, 1, battery_pct=20, battery_charging=False)
    assert len(mine()) == 1
    _battery(factory, device_id, private, 2, battery_pct=22, battery_charging=True)
    assert mine() == []  # plugged in: episode ends
    _battery(factory, device_id, private, 3, battery_pct=19, battery_charging=False)
    assert len(mine()) == 1  # unplugged again while low: a new episode warns once more
