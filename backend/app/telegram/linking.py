"""One-time codes that bind a private Telegram chat to a platform account."""

import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.db.enums import AccountStatus
from app.db.models import TelegramLink, TelegramLinkCode, User

SessionFactory = Callable[[], Session]

CODE_TTL = timedelta(minutes=10)
# Crockford-style alphabet without 0/O/1/I/L/U to avoid reading mistakes.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 10  # ~49 bits; with 10-minute expiry and per-chat rate limits.


class InvalidLinkCode(Exception):
    pass


class AlreadyLinked(Exception):
    pass


@dataclass(frozen=True)
class LinkCode:
    code: str
    expires_at: datetime


def normalize_code(raw: str) -> str | None:
    cleaned = "".join(raw.split()).replace("-", "").upper()
    if len(cleaned) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in cleaned):
        return None
    return cleaned


def _digest(code: str) -> bytes:
    return hashlib.sha256(("telegram-link:" + code).encode("ascii")).digest()


def _now(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def create_link_code(session_factory: SessionFactory, *, user_id: uuid.UUID) -> LinkCode:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    with session_factory() as session, session.begin():
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status is not AccountStatus.ACTIVE:
            raise InvalidLinkCode
        now = _now(session)
        # A new code supersedes any live one for this user.
        session.execute(
            delete(TelegramLinkCode).where(
                TelegramLinkCode.user_id == user_id, TelegramLinkCode.consumed_at.is_(None)
            )
        )
        session.add(
            TelegramLinkCode(
                user_id=user_id,
                code_digest=_digest(code),
                created_at=now,
                expires_at=now + CODE_TTL,
            )
        )
    return LinkCode(code=code, expires_at=now + CODE_TTL)


def consume_link_code(
    session_factory: SessionFactory, *, raw_code: str, chat_id: int, telegram_user_id: int
) -> uuid.UUID:
    code = normalize_code(raw_code)
    if code is None:
        raise InvalidLinkCode
    try:
        with session_factory() as session, session.begin():
            now = _now(session)
            row = session.scalar(
                select(TelegramLinkCode)
                .where(TelegramLinkCode.code_digest == _digest(code))
                .with_for_update()
            )
            if row is None or row.consumed_at is not None or row.expires_at <= now:
                raise InvalidLinkCode
            user = session.scalar(select(User).where(User.id == row.user_id).with_for_update())
            if user is None or user.status is not AccountStatus.ACTIVE:
                raise InvalidLinkCode
            existing_chat = session.scalar(
                select(TelegramLink).where(TelegramLink.chat_id == chat_id)
            )
            if existing_chat is not None and existing_chat.user_id != row.user_id:
                raise AlreadyLinked
            row.consumed_at = now
            # Re-linking replaces the user's previous chat.
            session.execute(delete(TelegramLink).where(TelegramLink.user_id == row.user_id))
            session.flush()
            session.add(
                TelegramLink(
                    user_id=row.user_id,
                    chat_id=chat_id,
                    telegram_user_id=telegram_user_id,
                    created_at=now,
                )
            )
            audit.record(session, user_id=row.user_id, action="telegram.linked", actor="telegram")
            return row.user_id
    except IntegrityError as error:
        raise AlreadyLinked from error


def linked_user_id(session: Session, *, chat_id: int, telegram_user_id: int) -> uuid.UUID | None:
    link = session.scalar(select(TelegramLink).where(TelegramLink.chat_id == chat_id))
    if link is None or link.telegram_user_id != telegram_user_id:
        return None
    user_status = session.scalar(select(User.status).where(User.id == link.user_id))
    if user_status is not AccountStatus.ACTIVE:
        return None
    return link.user_id


def unlink_chat(session_factory: SessionFactory, *, chat_id: int) -> bool:
    with session_factory() as session, session.begin():
        user_id = session.scalar(
            select(TelegramLink.user_id).where(TelegramLink.chat_id == chat_id)
        )
        result = session.execute(delete(TelegramLink).where(TelegramLink.chat_id == chat_id))
        removed = bool(getattr(result, "rowcount", 0))
        if removed:
            audit.record(session, user_id=user_id, action="telegram.unlinked", actor="telegram")
        return removed


def unlink_user(session_factory: SessionFactory, *, user_id: uuid.UUID) -> None:
    with session_factory() as session, session.begin():
        result = session.execute(delete(TelegramLink).where(TelegramLink.user_id == user_id))
        if getattr(result, "rowcount", 0):
            audit.record(session, user_id=user_id, action="telegram.unlinked", actor="user")
        session.execute(
            delete(TelegramLinkCode).where(
                TelegramLinkCode.user_id == user_id, TelegramLinkCode.consumed_at.is_(None)
            )
        )


def is_linked(session_factory: SessionFactory, *, user_id: uuid.UUID) -> bool:
    with session_factory() as session:
        return (
            session.scalar(select(TelegramLink.id).where(TelegramLink.user_id == user_id))
            is not None
        )
