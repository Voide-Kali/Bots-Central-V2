"""Telegram bot process: ``python -m app.telegram.bot``.

Long polling only (no inbound port). Requires TELEGRAM_BOT_TOKEN,
DATABASE_URL and ABUSE_CONTROL_HMAC_KEY; refuses to start without them.
"""

import logging
import signal
import time
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from app.assistant.ollama import OllamaClient
from app.auth.abuse_control import AbuseControlKey, AbuseController
from app.auth.email_verification_delivery import SmtpEmailVerificationDeliveryAdapter
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.devices import commands
from app.telegram.alerts import collect_presence_alerts
from app.telegram.client import TelegramClient, TelegramUnavailable
from app.telegram.commands import ActionDeps, Reply, handle_update
from app.telegram.resource_alerts import ResourceAlerter

ALERT_INTERVAL_SECONDS = 15
logger = logging.getLogger("bots_central.telegram")


def _send(client: TelegramClient, replies: list[Reply]) -> None:
    for reply in replies:
        if reply.callback_id is not None:
            try:
                client.answer_callback(reply.callback_id)
            except TelegramUnavailable:
                logger.warning("telegram callback answer failed")
        if reply.delete_message_id is not None and reply.delete_message_id > 0:
            try:
                client.delete_message(reply.chat_id, reply.delete_message_id)
            except TelegramUnavailable:
                logger.warning("telegram delete failed")
        try:
            client.send_message(reply.chat_id, reply.text, reply.keyboard)
        except TelegramUnavailable:
            logger.warning("telegram send failed")


def _deliver_files(client: TelegramClient, factory: sessionmaker[Session]) -> None:
    deliveries, notices = commands.pending_deliveries(factory)
    _send(client, [Reply(notice.chat_id, notice.text) for notice in notices])
    for item in deliveries:
        try:
            client.send_document(
                item.chat_id,
                item.file_name,
                item.content,
                caption=f"{item.file_name} — enviado por {item.device_name} (aprovado por você)",
            )
        except TelegramUnavailable:
            logger.warning("telegram document send failed")
            continue
        commands.mark_delivered(factory, command_id=item.command_id)


def run() -> None:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    client = TelegramClient(settings.telegram_bot_token)
    factory = sessionmaker(bind=get_engine())
    admission = AbuseController(factory, AbuseControlKey.from_settings(settings))
    actions: ActionDeps | None = None
    try:
        actions = ActionDeps(
            key=AbuseControlKey.from_settings(settings),
            mailer=SmtpEmailVerificationDeliveryAdapter.from_settings(settings),
        )
    except Exception:
        logger.warning("file actions disabled: SMTP or abuse key not configured")
    model = (
        OllamaClient(settings.assistant_ollama_url, settings.assistant_model)
        if settings.assistant_ollama_url
        else None
    )
    resources = ResourceAlerter()
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
            try:
                _send(client, resources.collect(factory))
            except Exception:
                logger.exception("resource alert pass failed")
            try:
                _deliver_files(client, factory)
            except Exception:
                logger.exception("file delivery pass failed")
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
                reply = handle_update(
                    update,
                    session_factory=factory,
                    admission=admission,
                    model=model,
                    actions=actions,
                )
            except Exception:
                logger.exception("telegram update handling failed")
                continue
            if reply is not None:
                _send(client, [reply])
    logger.info("telegram bot stopped")


if __name__ == "__main__":
    configure_logging(get_settings().log_level)
    run()
