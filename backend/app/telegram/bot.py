"""Telegram bot process: ``python -m app.telegram.bot``.

Long polling only (no inbound port). Requires TELEGRAM_BOT_TOKEN,
DATABASE_URL and ABUSE_CONTROL_HMAC_KEY; refuses to start without them.
"""

import logging
import signal
import time
from types import FrameType

from sqlalchemy.orm import sessionmaker

from app.auth.abuse_control import AbuseControlKey, AbuseController
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.telegram.alerts import collect_presence_alerts
from app.telegram.client import TelegramClient, TelegramUnavailable
from app.telegram.commands import Reply, handle_update

ALERT_INTERVAL_SECONDS = 30
logger = logging.getLogger("bots_central.telegram")


def _send(client: TelegramClient, replies: list[Reply]) -> None:
    for reply in replies:
        try:
            client.send_message(reply.chat_id, reply.text)
        except TelegramUnavailable:
            logger.warning("telegram send failed")


def run() -> None:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    client = TelegramClient(settings.telegram_bot_token)
    factory = sessionmaker(bind=get_engine())
    admission = AbuseController(factory, AbuseControlKey.from_settings(settings))
    stopping = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    offset: int | None = None
    next_alert = 0.0
    backoff = 1.0
    logger.info("telegram bot started")
    while not stopping:
        if time.monotonic() >= next_alert:
            try:
                _send(client, collect_presence_alerts(factory))
            except Exception:
                logger.exception("presence alert pass failed")
            next_alert = time.monotonic() + ALERT_INTERVAL_SECONDS
        try:
            updates = client.get_updates(offset=offset, timeout=20)
            backoff = 1.0
        except TelegramUnavailable:
            logger.warning("telegram polling failed; retrying")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            continue
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            try:
                reply = handle_update(update, session_factory=factory, admission=admission)
            except Exception:
                logger.exception("telegram update handling failed")
                continue
            if reply is not None:
                _send(client, [reply])
    logger.info("telegram bot stopped")


if __name__ == "__main__":
    configure_logging(get_settings().log_level)
    run()
