"""Smart resource alerts (idea from the old Kali Bunker, read-only).

A metric must stay above its limit in every sample of the last ``WINDOW`` (at least
``SUSTAINED_SAMPLES`` samples spanning ``MIN_SPAN``) before the owner is warned, so the
1-second live samples of ADR-018 do not alert on a short peak, and each (device,
metric) pair is then quiet for ``COOLDOWN``. Cooldowns live in the bot process: a restart can repeat
one warning, never hide one.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.enums import DeviceLifecycleStatus
from app.db.models import Device, DeviceTelemetrySample, TelegramLink
from app.telegram.commands import Reply

SessionFactory = Callable[[], Session]

SUSTAINED_SAMPLES = 3
WINDOW = timedelta(seconds=80)
MIN_SPAN = timedelta(seconds=50)
MAX_SAMPLES = 200
COOLDOWN_SECONDS = 30 * 60
CPU_LIMIT = 90.0
RAM_LIMIT = 95.0
DISK_LIMIT = 90.0
TEMP_LIMIT = 85.0  # the agent already drops implausible sensors (> 110 °C)


def _ratio(used: int | None, total: int | None) -> float | None:
    return None if used is None or not total else used * 100 / total


def _metrics(sample: DeviceTelemetrySample) -> dict[str, float | None]:
    return {
        "cpu": sample.cpu_percent,
        "ram": _ratio(sample.memory_used_bytes, sample.memory_total_bytes),
        "disk": _ratio(sample.disk_used_bytes, sample.disk_total_bytes),
        "temp": sample.temperature_c,
    }


LIMITS = {"cpu": CPU_LIMIT, "ram": RAM_LIMIT, "disk": DISK_LIMIT, "temp": TEMP_LIMIT}
MESSAGES = {
    "cpu": "{name}: CPU em {value:.0f}% há alguns minutos.",
    "ram": "{name}: memória quase cheia ({value:.0f}%).",
    "disk": "{name}: disco em {value:.0f}%. Libere espaço.",
    "temp": "{name}: temperatura alta ({value:.0f} °C).",
}


@dataclass
class ResourceAlerter:
    clock: Callable[[], float] = time.monotonic
    _last: dict[tuple[uuid.UUID, str], float] = field(default_factory=dict)

    def collect(self, session_factory: SessionFactory) -> list[Reply]:
        replies: list[Reply] = []
        with session_factory() as session:
            now = cast(datetime, session.scalar(text("SELECT clock_timestamp()")))
            rows = session.execute(
                select(Device, TelegramLink.chat_id)
                .join(TelegramLink, TelegramLink.user_id == Device.user_id)
                .where(Device.lifecycle_status == DeviceLifecycleStatus.ACTIVE)
            ).all()
            for device, chat_id in rows:
                samples = session.scalars(
                    select(DeviceTelemetrySample)
                    .where(
                        DeviceTelemetrySample.device_id == device.id,
                        DeviceTelemetrySample.recorded_at >= now - WINDOW,
                    )
                    .order_by(DeviceTelemetrySample.recorded_at.desc())
                    .limit(MAX_SAMPLES)
                ).all()
                if len(samples) < SUSTAINED_SAMPLES:
                    continue
                if samples[0].recorded_at - samples[-1].recorded_at < MIN_SPAN:
                    continue
                values = [_metrics(sample) for sample in samples]
                for metric, limit in LIMITS.items():
                    series = [item[metric] for item in values]
                    if any(value is None or value < limit for value in series):
                        continue
                    key = (device.id, metric)
                    last = self._last.get(key)
                    if last is not None and self.clock() - last < COOLDOWN_SECONDS:
                        continue
                    self._last[key] = self.clock()
                    latest = cast(float, series[0])
                    text_ = MESSAGES[metric].format(name=device.name, value=latest)
                    replies.append(Reply(chat_id, text_))
        return replies
