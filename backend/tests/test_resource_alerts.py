"""Smart resource alerts: sustained limits, cooldown, owner-only delivery."""

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
from app.telegram.resource_alerts import COOLDOWN_SECONDS, ResourceAlerter


@pytest.fixture
def factory(
    migrated_postgresql_engine: Engine, request: pytest.FixtureRequest
) -> Generator[sessionmaker[Session], None, None]:
    request.getfixturevalue("pg_cleanup")
    made = sessionmaker(bind=migrated_postgresql_engine)
    yield made
    with made() as session, session.begin():
        session.execute(delete(TelegramLink).where(TelegramLink.chat_id == CHAT))


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _hot(**changes: Any) -> dict[str, Any]:
    return {**VALID, **changes}


@pytest.mark.postgresql
def test_alert_needs_three_hot_samples_and_respects_cooldown(
    factory: sessionmaker[Session],
) -> None:
    user_id, device_id, private = _active_device(factory)
    _link(factory, user_id)
    clock = _Clock()
    alerter = ResourceAlerter(clock=clock)

    def mine() -> list[str]:
        return [r.text for r in alerter.collect(factory) if r.chat_id == CHAT]

    device_online.heartbeat(
        factory, device_id=device_id, jws=_beat(private, device_id, 1, _hot(cpu_pct=99.0))
    )
    device_online.heartbeat(
        factory, device_id=device_id, jws=_beat(private, device_id, 2, _hot(cpu_pct=97.0))
    )
    assert mine() == []  # only two samples
    device_online.heartbeat(
        factory, device_id=device_id, jws=_beat(private, device_id, 3, _hot(cpu_pct=12.0))
    )
    assert mine() == []  # dipped below the limit
    for seq in (4, 5, 6):
        device_online.heartbeat(
            factory,
            device_id=device_id,
            jws=_beat(private, device_id, seq, _hot(cpu_pct=96.0, temp_c=90.0)),
        )
    texts = mine()
    assert any("CPU em 96%" in text for text in texts)
    assert any("temperatura alta (90 °C)" in text for text in texts)
    assert mine() == []  # cooldown
    clock.now += COOLDOWN_SECONDS + 1
    assert len(mine()) == 2
