"""Password recovery by a one-time e-mail code (ADR-014).

Flow: request(email) always looks the same to the caller; only an ACTIVE
account with a verified primary e-mail gets a code. confirm(email, code,
new_password) checks the keyed HMAC in constant time, allows at most
MAX_ATTEMPTS wrong guesses per code, and on success replaces the Argon2id hash,
bumps ``users.security_version`` (which invalidates every existing session and
refresh token) and revokes the sessions explicitly.
"""

import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.auth.abuse_control import AbuseControlKey
from app.auth.emails import EmailValidationError, validate_and_canonicalize_email
from app.auth.passwords import hash_password, validate_password
from app.db.enums import AccountStatus, SessionRevocationReason
from app.db.models import PasswordCredential, PasswordResetCode, User, UserEmail
from app.db.models import Session as DbSession

SessionFactory = Callable[[], Session]
CODE_TTL = timedelta(minutes=15)
MAX_ATTEMPTS = 5
CODE_DIGITS = 8


@dataclass(frozen=True)
class ResetIntent:
    recipient: str = field(repr=False)
    code: SecretStr = field(repr=False)
    expires_at: datetime


def _mac(key: AbuseControlKey, user_id: uuid.UUID, code: str) -> bytes:
    return key.pseudonymize("password-reset-code", f"{user_id}:{code}")


def _now(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def _locate(session: Session, email: str) -> tuple[User, UserEmail] | None:
    try:
        canonical = validate_and_canonicalize_email(email).canonical
    except EmailValidationError:
        return None
    row = session.scalar(
        select(UserEmail).where(
            UserEmail.email_canonical == canonical, UserEmail.is_primary.is_(True)
        )
    )
    if row is None or row.verified_at is None:
        return None
    user = session.scalar(select(User).where(User.id == row.user_id).with_for_update())
    if user is None or user.status is not AccountStatus.ACTIVE:
        return None
    return user, row


def request_reset(
    session_factory: SessionFactory, key: AbuseControlKey, *, email: str
) -> ResetIntent | None:
    """Return a delivery intent only for eligible accounts; callers must answer identically."""
    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    with session_factory() as session, session.begin():
        located = _locate(session, email)
        if located is None:
            return None
        user, email_row = located
        has_password = session.scalar(
            select(PasswordCredential.user_id).where(PasswordCredential.user_id == user.id)
        )
        if has_password is None:
            return None
        now = _now(session)
        session.execute(
            delete(PasswordResetCode).where(
                PasswordResetCode.user_id == user.id, PasswordResetCode.consumed_at.is_(None)
            )
        )
        session.add(
            PasswordResetCode(
                user_id=user.id,
                code_mac=_mac(key, user.id, code),
                created_at=now,
                expires_at=now + CODE_TTL,
            )
        )
        audit.record(session, user_id=user.id, action="auth.password_reset_requested", actor="user")
        return ResetIntent(
            recipient=email_row.email_display, code=SecretStr(code), expires_at=now + CODE_TTL
        )


def confirm_reset(
    session_factory: SessionFactory,
    key: AbuseControlKey,
    *,
    email: str,
    code: str,
    new_password: str,
) -> bool:
    """True only when the code matched and the password was replaced.

    Raises ``PasswordPolicyError`` before touching the database for a weak password.
    Wrong guesses are committed (attempt counter) and return False.
    """
    validate_password(new_password)
    if len(code) != CODE_DIGITS or not code.isascii() or not code.isdigit():
        return False
    new_hash = hash_password(new_password)
    with session_factory() as session, session.begin():
        located = _locate(session, email)
        if located is None:
            return False
        user, _ = located
        now = _now(session)
        row = session.scalar(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.consumed_at.is_(None),
                PasswordResetCode.expires_at > now,
            )
            .order_by(PasswordResetCode.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if row is None or row.attempts >= MAX_ATTEMPTS:
            return False
        if not hmac.compare_digest(row.code_mac, _mac(key, user.id, code)):
            row.attempts += 1
            audit.record(
                session,
                user_id=user.id,
                action="auth.password_reset_failed",
                actor="user",
                outcome="denied",
            )
            return False
        credential = session.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.user_id == user.id)
            .with_for_update()
        )
        if credential is None:
            return False
        credential.password_hash = new_hash
        row.consumed_at = now
        user.security_version += 1
        sessions = session.scalars(
            select(DbSession)
            .where(DbSession.user_id == user.id, DbSession.revoked_at.is_(None))
            .with_for_update()
        ).all()
        for db_session in sessions:
            db_session.revoked_at = now
            db_session.revocation_reason = SessionRevocationReason.PASSWORD_RESET
        audit.record(session, user_id=user.id, action="auth.password_reset_completed", actor="user")
        return True
