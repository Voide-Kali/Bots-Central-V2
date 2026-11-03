"""Telegram bot process: ``python -m app.telegram.bot``.

Long polling only (no inbound port). Requires TELEGRAM_BOT_TOKEN,
DATABASE_URL and ABUSE_CONTROL_HMAC_KEY; refuses to start without them.
"""

import logging
import signal
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from types import FrameType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.assistant.assistant import Conversations
from app.assistant.ollama import OllamaClient
from app.auth.abuse_control import AbuseControlKey, AbuseController
from app.auth.email_verification_delivery import SmtpEmailVerificationDeliveryAdapter
from app.auth.emails import EmailValidationError, validate_and_canonicalize_email
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.models import UserEmail
from app.db.session import get_engine
from app.devices import commands, events
from app.inbox.gmail_api import GmailApiProvider
from app.inbox.inbox import EmailFilter, EmailTarget, MailProvider, collect_email_notices
from app.telegram.alerts import collect_presence_alerts
from app.telegram.client import TelegramClient, TelegramUnavailable
from app.telegram.commands import ActionDeps, Reply, handle_update
from app.telegram.resource_alerts import ResourceAlerter

ALERT_INTERVAL_SECONDS = 15
EMAIL_INTERVAL_SECONDS = 60  # Gmail is polled less often than device alerts (API quota)
CLEANUP_INTERVAL_SECONDS = 3600
logger = logging.getLogger("bots_central.telegram")


def _send(client: TelegramClient, replies: list[Reply]) -> None:
    for reply in replies:
        if reply.callback_id is not None:
            try:
                client.answer_callback(reply.callback_id)
            except TelegramUnavailable:
                logger.warning("telegram callback answer failed")
        if reply.remove_reply_keyboard:
            # One message clears any leftover persistent bottom keyboard; the inline menu,
            # if any, follows as a second message (the two cannot share one reply_markup).
            try:
                client.send_message(reply.chat_id, reply.text, {"remove_keyboard": True})
            except TelegramUnavailable:
                logger.warning("telegram keyboard removal failed")
            if reply.keyboard is not None and "inline_keyboard" in reply.keyboard:
                try:
                    client.send_message(reply.chat_id, "Escolha uma opção:", reply.keyboard)
                except TelegramUnavailable:
                    logger.warning("telegram menu send failed")
            continue
        if reply.delete_message_id is not None and reply.delete_message_id > 0:
            try:
                client.delete_message(reply.chat_id, reply.delete_message_id)
            except TelegramUnavailable:
                logger.warning("telegram delete failed")
        if reply.edit_message_id is not None:
            try:
                client.edit_message(
                    reply.chat_id, reply.edit_message_id, reply.text, reply.keyboard
                )
            except TelegramUnavailable:
                # Usually "message is not modified" (Atualizar with nothing new).
                logger.info("telegram edit skipped")
            continue
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


def _deliver_events(client: TelegramClient, factory: sessionmaker[Session]) -> None:
    """ADR-019: wrong-password warnings, with the photo when the computer took one."""
    for item in events.pending_events(factory):
        try:
            if item.photo:
                client.send_photo(item.chat_id, item.photo, item.caption)
            else:
                client.send_message(item.chat_id, item.caption)
        except TelegramUnavailable:
            logger.warning("telegram event send failed")
            continue
        events.mark_delivered(factory, event_id=item.event_id)


@dataclass(frozen=True)
class EmailWatch:
    provider: MailProvider
    targets: list[EmailTarget]
    email_filter: EmailFilter


def _split_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in value.split(",") if token.strip())


def _email_watch(settings: Settings, factory: sessionmaker[Session]) -> EmailWatch | None:
    """Build the Gmail watch once at startup, or None when e-mail notices are off.

    Resolves the owner's user id from EMAIL_OWNER so every new e-mail is announced to that
    account's linked Telegram. Everything here is read-only (gmail.readonly, ADR-024). The
    owner's Aval account must already exist; restart the bot after creating it.
    """
    if not (settings.gmail_token_file and settings.gmail_account and settings.email_owner):
        return None
    try:
        canonical = validate_and_canonicalize_email(settings.email_owner).canonical
    except EmailValidationError:
        logger.warning("email notices disabled: EMAIL_OWNER is not a valid e-mail")
        return None
    with factory() as session:
        owner_id = session.scalar(
            select(UserEmail.user_id).where(
                UserEmail.email_canonical == canonical, UserEmail.is_primary.is_(True)
            )
        )
    if owner_id is None:
        logger.warning("email notices disabled: no Aval account matches EMAIL_OWNER")
        return None
    provider = GmailApiProvider(
        token_file=settings.gmail_token_file,
        timeout_seconds=settings.gmail_api_timeout_seconds,
        max_results=settings.gmail_max_per_check,
    )
    email_filter = EmailFilter(
        ignore_senders=_split_tokens(settings.email_ignore_senders),
        ignore_sender_domains=_split_tokens(settings.email_ignore_sender_domains),
        ignore_subject_keywords=_split_tokens(settings.email_ignore_subject_keywords),
    )
    logger.info("email notices enabled (gmail) for %s", settings.gmail_account)
    return EmailWatch(
        provider=provider,
        targets=[EmailTarget(user_id=owner_id, account=settings.gmail_account)],
        email_filter=email_filter,
    )


def _deliver_emails(
    client: TelegramClient,
    factory: sessionmaker[Session],
    model: OllamaClient | None,
    watch: EmailWatch,
) -> None:
    """Announce new e-mails, each with a local-AI one-line summary (ADR-024)."""
    notices = collect_email_notices(
        factory, watch.provider, model, watch.targets, email_filter=watch.email_filter
    )
    _send(client, [Reply(notice.chat_id, notice.text) for notice in notices])


def _chat_of(update: dict[str, Any]) -> int | None:
    callback = update.get("callback_query")
    message = callback.get("message") if isinstance(callback, dict) else update.get("message")
    chat = message.get("chat") if isinstance(message, dict) else None
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    return chat_id if isinstance(chat_id, int) else None


class ChatQueue:
    """Handle updates in worker threads, keeping each chat's updates in order.

    A slow answer from the local AI no longer holds every other chat (and alerts) back,
    while a PIN typed after a request in the same chat is still handled after it.
    """

    def __init__(self, workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tg")
        self._last: dict[int, Future[None]] = {}

    def submit(self, chat_id: int | None, job: Callable[[], None]) -> Future[None]:
        key = chat_id if chat_id is not None else 0
        previous = self._last.get(key)

        def run() -> None:
            if previous is not None:
                try:
                    previous.result()
                except Exception:  # noqa: S110 - the earlier job already logged its failure
                    pass
            job()

        future = self._pool.submit(run)
        self._last[key] = future
        for done in [chat for chat, item in self._last.items() if item.done()]:
            if self._last[done] is not future:
                del self._last[done]
        return future

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


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
    conversations = Conversations()
    email_watch = _email_watch(settings, factory)
    queue = ChatQueue()
    stopping = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    offset: int | None = None
    next_alert = 0.0
    next_email = 0.0
    next_cleanup = 0.0
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
            try:
                _deliver_events(client, factory)
            except Exception:
                logger.exception("event delivery pass failed")
            next_alert = time.monotonic() + ALERT_INTERVAL_SECONDS
        if email_watch is not None and time.monotonic() >= next_email:
            try:
                _deliver_emails(client, factory, model, email_watch)
            except Exception:
                logger.exception("email notify pass failed")
            next_email = time.monotonic() + EMAIL_INTERVAL_SECONDS
        if time.monotonic() >= next_cleanup:
            # Expired rate-limit rows are never read again; drop them once an hour.
            try:
                admission.cleanup_expired()
            except Exception:
                logger.warning("rate-limit cleanup failed")
            next_cleanup = time.monotonic() + CLEANUP_INTERVAL_SECONDS
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

            def job(update: dict[str, Any] = update) -> None:
                try:
                    reply = handle_update(
                        update,
                        session_factory=factory,
                        admission=admission,
                        model=model,
                        actions=actions,
                        conversations=conversations,
                    )
                except Exception:
                    logger.exception("telegram update handling failed")
                    return
                if reply is not None:
                    _send(client, [reply])

            queue.submit(_chat_of(update), job)
    queue.shutdown()
    logger.info("telegram bot stopped")


if __name__ == "__main__":
    configure_logging(get_settings().log_level)
    run()
