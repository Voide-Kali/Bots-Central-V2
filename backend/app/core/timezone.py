"""Times shown to people (Telegram texts, photo names) use the owner's local time.

PostgreSQL in the server container runs in UTC, so a timestamp printed as is was 4 hours
ahead for Campo Grande. ``DISPLAY_TIMEZONE`` can change the zone; without tz data in the
image, the fixed offset of Mato Grosso do Sul (UTC-4, no daylight saving since 2019) is used.
"""

import os
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _zone() -> tzinfo:
    name = os.environ.get("DISPLAY_TIMEZONE", "America/Campo_Grande")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(hours=-4), "UTC-4")


DISPLAY_TZ = _zone()


def local(moment: datetime) -> datetime:
    """The same instant in the display zone (naive values are taken as UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(DISPLAY_TZ)
