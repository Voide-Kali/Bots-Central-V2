"""Email-verification consumption staged in the caller's outer transaction."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationLinkToken,
    InvalidHumanEmailCode,
    UnknownEmailVerificationHmacKeyVersion,
    digest_external_link_token,
    normalize_human_email_code,
    verify_email_verification_code_digest,
)
from app.db.enums import (
    AccountStatus,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
)
from app.db.models import EmailVerificationChallenge, User, UserEmail


class EmailVerificationConsumeTransactionStateError(RuntimeError):
    """Raised before any query/savepoint can flush caller-owned pending state."""


class EmailVerificationConsumeInvariantError(RuntimeError):
    """Raised when database state contradicts required persistence invariants."""


@dataclass(frozen=True)
class ConsumedEmailVerification:
    """Staged success; durable only after the caller commits."""

    challenge_id: uuid.UUID
    user_email_id: uuid.UUID
    consumed_at: datetime


@dataclass(frozen=True)
class WrongCode:
    attempt_count: int
    attempts_remaining: int


@dataclass(frozen=True)
class AttemptsExhausted:
    pass


@dataclass(frozen=True)
class MalformedCode:
    pass


@dataclass(frozen=True)
class InvalidChallenge:
    pass


@dataclass(frozen=True)
class Expired:
    pass


@dataclass(frozen=True)
class AlreadyConsumed:
    pass


@dataclass(frozen=True)
class Invalidated:
    invalidation_reason: EmailVerificationInvalidationReason


@dataclass(frozen=True)
class AlreadyVerified:
    user_email_id: uuid.UUID


@dataclass(frozen=True)
class AccountNotEligible:
    user_email_id: uuid.UUID
    account_status: AccountStatus


@dataclass(frozen=True)
class KeyVersionUnavailable:
    pass


EmailVerificationConsumeOutcome = (
    ConsumedEmailVerification
    | WrongCode
    | AttemptsExhausted
    | MalformedCode
    | InvalidChallenge
    | Expired
    | AlreadyConsumed
    | Invalidated
    | AlreadyVerified
    | AccountNotEligible
    | KeyVersionUnavailable
)


def _require_clean_session(session: DatabaseSession) -> None:
    if session.new or session.dirty or session.deleted:
        raise EmailVerificationConsumeTransactionStateError(
            "email verification consume requires a session without pending new, dirty, "
            "or deleted state"
        )


def _invalidate(
    session: DatabaseSession,
    challenge: EmailVerificationChallenge,
    decision_time: datetime,
    reason: EmailVerificationInvalidationReason,
) -> None:
    challenge.invalidated_at = decision_time
    challenge.invalidation_reason = reason
    session.flush()


def _lock_and_revalidate(
    session: DatabaseSession,
    *,
    candidate_id: uuid.UUID,
    candidate_email_id: uuid.UUID,
    material_type: EmailVerificationMaterialType,
    requested_digest: bytes | None = None,
) -> tuple[UserEmail, User, EmailVerificationChallenge, datetime] | (
    InvalidChallenge
    | AlreadyConsumed
    | Invalidated
    | Expired
    | AlreadyVerified
    | AccountNotEligible
):
    # Locator values identify lock targets only. Never use a cached ORM entity here.
    user_email = session.scalar(
        select(UserEmail)
        .where(UserEmail.id == candidate_email_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user_email is None:
        return InvalidChallenge()
    user = session.scalar(
        select(User)
        .where(User.id == user_email.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise EmailVerificationConsumeInvariantError("user email references a missing user")
    challenge = session.scalar(
        select(EmailVerificationChallenge)
        .where(EmailVerificationChallenge.id == candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    decision_time = session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(decision_time, datetime):
        raise EmailVerificationConsumeInvariantError(
            "PostgreSQL clock_timestamp() returned no timestamp"
        )
    if (
        challenge is None
        or challenge.id != candidate_id
        or challenge.user_email_id != user_email.id
        or challenge.material_type is not material_type
        or (
            material_type is EmailVerificationMaterialType.LINK
            and challenge.link_token_digest != requested_digest
        )
    ):
        return InvalidChallenge()
    if challenge.consumed_at is not None:
        return AlreadyConsumed()
    if challenge.invalidated_at is not None:
        if challenge.invalidation_reason is None:
            raise EmailVerificationConsumeInvariantError("invalidated challenge has no reason")
        return Invalidated(invalidation_reason=challenge.invalidation_reason)
    if decision_time >= challenge.expires_at:
        return Expired()
    if user_email.verified_at is not None:
        _invalidate(
            session,
            challenge,
            decision_time,
            EmailVerificationInvalidationReason.EMAIL_ALREADY_VERIFIED,
        )
        return AlreadyVerified(user_email_id=user_email.id)
    if user.status is not AccountStatus.PENDING_VERIFICATION:
        _invalidate(
            session,
            challenge,
            decision_time,
            EmailVerificationInvalidationReason.ACCOUNT_STATE_CHANGED,
        )
        return AccountNotEligible(user_email_id=user_email.id, account_status=user.status)
    return user_email, user, challenge, decision_time


def _consume(
    session: DatabaseSession,
    user_email: UserEmail,
    user: User,
    challenge: EmailVerificationChallenge,
    decision_time: datetime,
) -> ConsumedEmailVerification:
    challenge.consumed_at = decision_time
    user_email.verified_at = decision_time
    user.status = AccountStatus.ACTIVE
    # Override model onupdate=now(): all operation timestamps share post-lock time.
    user_email.updated_at = decision_time
    user.updated_at = decision_time
    siblings = session.scalars(
        select(EmailVerificationChallenge)
        .where(
            EmailVerificationChallenge.user_email_id == user_email.id,
            EmailVerificationChallenge.id != challenge.id,
            EmailVerificationChallenge.consumed_at.is_(None),
            EmailVerificationChallenge.invalidated_at.is_(None),
            EmailVerificationChallenge.expires_at > decision_time,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for sibling in siblings:
        sibling.invalidated_at = decision_time
        sibling.invalidation_reason = EmailVerificationInvalidationReason.EMAIL_ALREADY_VERIFIED
    session.flush()
    return ConsumedEmailVerification(
        challenge_id=challenge.id, user_email_id=user_email.id, consumed_at=decision_time
    )


def consume_email_verification_code(
    session: DatabaseSession,
    *,
    challenge_id: uuid.UUID,
    code: str,
    keyring: EmailVerificationHmacKeyring,
) -> EmailVerificationConsumeOutcome:
    """Stage consume or attempt accounting without committing/rolling back the caller.

    WrongCode and AttemptsExhausted are normal, committable results. The caller must
    commit the outer transaction before future HTTP serialization or external I/O.
    Locks remain UserEmail -> User -> Challenge, including after a stale locator.
    """
    if not isinstance(challenge_id, uuid.UUID):
        raise TypeError("challenge_id must be a UUID")
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    if not isinstance(keyring, EmailVerificationHmacKeyring):
        raise TypeError("keyring must be an EmailVerificationHmacKeyring")
    _require_clean_session(session)
    with session.begin_nested():
        candidate = session.execute(
            select(EmailVerificationChallenge.id, EmailVerificationChallenge.user_email_id).where(
                EmailVerificationChallenge.id == challenge_id
            )
        ).one_or_none()
        if candidate is None:
            return InvalidChallenge()
        locked = _lock_and_revalidate(
            session,
            candidate_id=candidate.id,
            candidate_email_id=candidate.user_email_id,
            material_type=EmailVerificationMaterialType.CODE,
        )
        if not isinstance(locked, tuple):
            return locked
        user_email, user, challenge, decision_time = locked
        try:
            normalized_code = normalize_human_email_code(code)
        except InvalidHumanEmailCode:
            return MalformedCode()
        if (
            challenge.attempt_count is None
            or challenge.max_attempts != 5
            or not 0 <= challenge.attempt_count <= challenge.max_attempts
            or challenge.code_digest is None
            or len(challenge.code_digest) != 32
            or not challenge.hmac_key_version
        ):
            raise EmailVerificationConsumeInvariantError(
                "code challenge has invalid material fields"
            )
        if challenge.attempt_count >= challenge.max_attempts:
            _invalidate(
                session,
                challenge,
                decision_time,
                EmailVerificationInvalidationReason.ATTEMPTS_EXHAUSTED,
            )
            return AttemptsExhausted()
        try:
            key = keyring.key_for_version(challenge.hmac_key_version)
        except UnknownEmailVerificationHmacKeyVersion:
            return KeyVersionUnavailable()
        if not verify_email_verification_code_digest(
            expected_digest=challenge.code_digest,
            key=key,
            challenge_id=challenge.id,
            user_id=user.id,
            user_email_id=user_email.id,
            code=normalized_code,
        ):
            challenge.attempt_count += 1
            if challenge.attempt_count == challenge.max_attempts:
                _invalidate(
                    session,
                    challenge,
                    decision_time,
                    EmailVerificationInvalidationReason.ATTEMPTS_EXHAUSTED,
                )
                return AttemptsExhausted()
            session.flush()
            return WrongCode(
                attempt_count=challenge.attempt_count,
                attempts_remaining=challenge.max_attempts - challenge.attempt_count,
            )
        return _consume(session, user_email, user, challenge, decision_time)


def consume_email_verification_link(
    session: DatabaseSession, *, external_token: str
) -> EmailVerificationConsumeOutcome:
    """Stage link consume with the same locks/transition as CODE; no keyring required."""
    if not isinstance(external_token, str):
        raise TypeError("external_token must be a string")
    _require_clean_session(session)
    try:
        requested_digest = digest_external_link_token(external_token)
    except InvalidEmailVerificationLinkToken:
        return InvalidChallenge()
    with session.begin_nested():
        candidate = session.execute(
            select(EmailVerificationChallenge.id, EmailVerificationChallenge.user_email_id).where(
                EmailVerificationChallenge.link_token_digest == requested_digest
            )
        ).one_or_none()
        if candidate is None:
            return InvalidChallenge()
        locked = _lock_and_revalidate(
            session,
            candidate_id=candidate.id,
            candidate_email_id=candidate.user_email_id,
            material_type=EmailVerificationMaterialType.LINK,
            requested_digest=requested_digest,
        )
        if not isinstance(locked, tuple):
            return locked
        return _consume(session, *locked)
