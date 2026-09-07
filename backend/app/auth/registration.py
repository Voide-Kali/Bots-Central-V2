"""Atomic domain registration service without transport or session creation."""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.emails import validate_and_canonicalize_email
from app.auth.passwords import hash_password
from app.db.enums import AccountStatus
from app.db.models import PasswordCredential, User, UserEmail

PASSWORD_HASH_VERSION = "argon2id-v1"
_EMAIL_CANONICAL_UNIQUE_CONSTRAINT = "user_emails_email_canonical_key"


class DuplicateEmailError(RuntimeError):
    """Raised internally when PostgreSQL rejects a duplicate canonical email."""


class RegistrationTransactionStateError(RuntimeError):
    """Raised when registration would flush pending caller-owned session state."""


@dataclass(frozen=True)
class RegistrationResult:
    """Non-sensitive outcome of a successful account registration."""

    user_id: uuid.UUID
    email_display: str
    account_status: AccountStatus


def _is_duplicate_canonical_email(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None) == _EMAIL_CANONICAL_UNIQUE_CONSTRAINT


def _require_clean_session(session: DatabaseSession) -> None:
    if session.new or session.dirty or session.deleted:
        raise RegistrationTransactionStateError(
            "registration requires a session without pending new, dirty, or deleted state"
        )


def register_user(
    session: DatabaseSession,
    *,
    email: str,
    password: str,
) -> RegistrationResult:
    """Stage an all-or-nothing pending account in the caller's transaction.

    The caller must provide a session without pending state. Validation and password
    hashing then finish before persistence. A nested transaction ensures this service
    leaves no partial records if its database work fails; the caller owns the enclosing
    transaction and its final commit or rollback.
    """
    _require_clean_session(session)
    canonical_email = validate_and_canonicalize_email(email)
    password_hash = hash_password(password)

    try:
        with session.begin_nested():
            user = User(status=AccountStatus.PENDING_VERIFICATION)
            session.add(user)
            session.flush()

            session.add_all(
                [
                    UserEmail(
                        user_id=user.id,
                        email_canonical=canonical_email.canonical,
                        email_display=canonical_email.display,
                        is_primary=True,
                    ),
                    PasswordCredential(
                        user_id=user.id,
                        password_hash=password_hash,
                        password_hash_version=PASSWORD_HASH_VERSION,
                    ),
                ]
            )
            session.flush()
    except IntegrityError as error:
        if _is_duplicate_canonical_email(error):
            raise DuplicateEmailError("canonical email is already registered") from error
        raise

    return RegistrationResult(
        user_id=user.id,
        email_display=canonical_email.display,
        account_status=user.status,
    )
