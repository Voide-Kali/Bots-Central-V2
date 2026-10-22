"""Personal action PIN (ADR-016 addendum, decided by the owner on 21/10/2026).

E-mail codes stay for registration and password reset; catalogue actions are
approved in Telegram with a 6-digit PIN the owner sets in the web panel.

* stored as HMAC(server key, user_id:pin): useless offline without the key;
* trivial PINs (000000, 123456, …) are refused;
* 5 wrong PINs lock approvals for 15 minutes; the counter resets on success;
* setting or changing the PIN requires the account password.
"""

import hmac
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit import events as audit
from app.auth.abuse_control import AbuseControlKey
from app.auth.passwords import verify_password
from app.db.models import ActionPin, PasswordCredential

SessionFactory = Callable[[], Session]

PIN_DIGITS = 6
MAX_FAILURES = 5
LOCK_TIME = timedelta(minutes=15)
WEAK_PINS = frozenset(
    {"123456", "654321", "123123", "112233", "121212", "000123", "012345", "987654"}
    | {str(d) * PIN_DIGITS for d in range(10)}
)


class PinPolicyError(ValueError):
    """The PIN is not 6 digits or is too easy to guess."""


class WrongPassword(Exception):
    pass


@dataclass(frozen=True)
class PinCheck:
    ok: bool
    locked_until: datetime | None = None
    remaining: int = 0
    configured: bool = True


def validate_pin(pin: str) -> None:
    if len(pin) != PIN_DIGITS or not pin.isascii() or not pin.isdigit():
        raise PinPolicyError("PIN must be 6 digits")
    if pin in WEAK_PINS:
        raise PinPolicyError("PIN too easy to guess")


def looks_like_pin(text_: str) -> bool:
    cleaned = text_.strip()
    return len(cleaned) == PIN_DIGITS and cleaned.isascii() and cleaned.isdigit()


def _mac(key: AbuseControlKey, user_id: uuid.UUID, pin: str) -> bytes:
    return key.pseudonymize("action-pin", f"{user_id}:{pin}")


def _now(session: Session) -> datetime:
    value = session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


def set_pin(
    session_factory: SessionFactory,
    key: AbuseControlKey,
    *,
    user_id: uuid.UUID,
    password: str,
    pin: str,
) -> None:
    validate_pin(pin)
    with session_factory() as session, session.begin():
        credential = session.scalar(
            select(PasswordCredential).where(PasswordCredential.user_id == user_id)
        )
        if credential is None or not verify_password(credential.password_hash, password):
            audit.record(
                session,
                user_id=user_id,
                action="pin.change_failed",
                actor="user",
                outcome="denied",
            )
            raise WrongPassword
        now = _now(session)
        row = session.get(ActionPin, user_id, with_for_update=True)
        if row is None:
            session.add(ActionPin(user_id=user_id, pin_mac=_mac(key, user_id, pin), updated_at=now))
        else:
            row.pin_mac = _mac(key, user_id, pin)
            row.failed_attempts = 0
            row.locked_until = None
            row.updated_at = now
        audit.record(session, user_id=user_id, action="pin.changed", actor="user")


def status(session: Session, user_id: uuid.UUID) -> tuple[bool, datetime | None]:
    row = session.get(ActionPin, user_id)
    if row is None:
        return False, None
    locked = row.locked_until if row.locked_until and row.locked_until > _now(session) else None
    return True, locked


def check_pin(session: Session, key: AbuseControlKey, *, user_id: uuid.UUID, pin: str) -> PinCheck:
    """Verify inside the caller's transaction (row locked); counts failures."""
    row = session.get(ActionPin, user_id, with_for_update=True)
    if row is None:
        return PinCheck(ok=False, configured=False)
    now = _now(session)
    if row.locked_until is not None and row.locked_until > now:
        return PinCheck(ok=False, locked_until=row.locked_until)
    if looks_like_pin(pin) and hmac.compare_digest(row.pin_mac, _mac(key, user_id, pin.strip())):
        row.failed_attempts = 0
        row.locked_until = None
        return PinCheck(ok=True)
    row.failed_attempts += 1
    if row.failed_attempts >= MAX_FAILURES:
        row.failed_attempts = 0
        row.locked_until = now + LOCK_TIME
        audit.record(
            session, user_id=user_id, action="pin.locked", actor="telegram", outcome="denied"
        )
        return PinCheck(ok=False, locked_until=row.locked_until)
    audit.record(session, user_id=user_id, action="pin.failed", actor="telegram", outcome="denied")
    return PinCheck(ok=False, remaining=MAX_FAILURES - row.failed_attempts)
