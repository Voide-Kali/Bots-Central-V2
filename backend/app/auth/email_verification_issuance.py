"""Synchronous, caller-transaction-owned email-verification issuance staging."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.email_verification_materials import (
    EmailVerificationHmacKeyring,
    InvalidEmailVerificationHmacConfiguration,
    email_verification_code_digest,
    generate_human_email_code,
    generate_link_token,
)
from app.db.enums import (
    AccountStatus,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
)
from app.db.models import EmailVerificationChallenge, User, UserEmail

EMAIL_VERIFICATION_COOLDOWN = timedelta(seconds=60)
LINK_CHALLENGE_TTL = timedelta(minutes=15)
CODE_CHALLENGE_TTL = timedelta(minutes=10)
CODE_CHALLENGE_MAX_ATTEMPTS = 5


class EmailVerificationIssuanceTransactionStateError(RuntimeError):
    """Raised before a savepoint could flush caller-owned pending state."""


class EmailVerificationIssuanceInvariantError(RuntimeError):
    """Raised when persisted relations contradict database invariants."""


@dataclass(frozen=True)
class StagedLinkChallenge:
    """Plaintext is usable only after the caller successfully commits."""

    challenge_id: uuid.UUID
    user_email_id: uuid.UUID
    expires_at: datetime
    external_token: SecretStr = field(repr=False)


@dataclass(frozen=True)
class StagedCodeChallenge:
    """Plaintext is usable only after the caller successfully commits."""

    challenge_id: uuid.UUID
    user_email_id: uuid.UUID
    expires_at: datetime
    code: SecretStr = field(repr=False)


@dataclass(frozen=True)
class CooldownActive:
    user_email_id: uuid.UUID
    retry_at: datetime


@dataclass(frozen=True)
class AlreadyVerified:
    user_email_id: uuid.UUID


@dataclass(frozen=True)
class AccountNotEligible:
    user_email_id: uuid.UUID
    account_status: AccountStatus


@dataclass(frozen=True)
class NotFound:
    user_email_id: uuid.UUID


EmailVerificationIssuanceOutcome = (
    StagedLinkChallenge
    | StagedCodeChallenge
    | CooldownActive
    | AlreadyVerified
    | AccountNotEligible
    | NotFound
)


def _require_clean_session(session: DatabaseSession) -> None:
    if session.new or session.dirty or session.deleted:
        raise EmailVerificationIssuanceTransactionStateError(
            "email verification issuance requires a session without pending new, dirty, "
            "or deleted state"
        )


def _decision_time(session: DatabaseSession) -> datetime:
    decision_time = session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(decision_time, datetime):
        raise EmailVerificationIssuanceInvariantError(
            "PostgreSQL clock_timestamp() returned no timestamp"
        )
    return decision_time


def stage_email_verification(
    session: DatabaseSession,
    *,
    user_email_id: uuid.UUID,
    material_type: EmailVerificationMaterialType,
    keyring: EmailVerificationHmacKeyring | None = None,
) -> EmailVerificationIssuanceOutcome:
    """Stage issuance/resend without committing the caller's transaction.

    PostgreSQL locks are acquired in ``UserEmail -> User -> Challenge`` order. The
    returned plaintext material is not durable or externally usable until the caller
    commits its outer transaction successfully; this function never performs delivery.
    """
    if not isinstance(user_email_id, uuid.UUID):
        raise TypeError("user_email_id must be a UUID")
    if not isinstance(material_type, EmailVerificationMaterialType):
        raise TypeError("material_type must be an EmailVerificationMaterialType")
    _require_clean_session(session)

    with session.begin_nested():
        user_email = session.scalar(
            select(UserEmail)
            .where(UserEmail.id == user_email_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user_email is None:
            return NotFound(user_email_id=user_email_id)

        user = session.scalar(
            select(User)
            .where(User.id == user_email.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise EmailVerificationIssuanceInvariantError(
                "user email references a missing user despite its foreign key"
            )

        decision_time = _decision_time(session)
        if user_email.verified_at is not None:
            return AlreadyVerified(user_email_id=user_email.id)
        if user.status is not AccountStatus.PENDING_VERIFICATION:
            return AccountNotEligible(user_email_id=user_email.id, account_status=user.status)

        latest_challenge = session.scalar(
            select(EmailVerificationChallenge)
            .where(EmailVerificationChallenge.user_email_id == user_email.id)
            .order_by(EmailVerificationChallenge.created_at.desc())
            .limit(1)
        )
        if latest_challenge is not None:
            retry_at = latest_challenge.created_at + EMAIL_VERIFICATION_COOLDOWN
            if decision_time < retry_at:
                return CooldownActive(user_email_id=user_email.id, retry_at=retry_at)

        live_siblings = list(
            session.scalars(
                select(EmailVerificationChallenge)
                .where(
                    EmailVerificationChallenge.user_email_id == user_email.id,
                    EmailVerificationChallenge.consumed_at.is_(None),
                    EmailVerificationChallenge.invalidated_at.is_(None),
                    EmailVerificationChallenge.expires_at > decision_time,
                )
                .with_for_update()
            )
        )

        challenge_id = uuid.uuid4()
        if material_type is EmailVerificationMaterialType.LINK:
            material = generate_link_token()
            challenge = EmailVerificationChallenge(
                id=challenge_id,
                user_email_id=user_email.id,
                material_type=EmailVerificationMaterialType.LINK,
                link_token_digest=material.digest,
                created_at=decision_time,
                expires_at=decision_time + LINK_CHALLENGE_TTL,
            )
            result: EmailVerificationIssuanceOutcome = StagedLinkChallenge(
                challenge_id=challenge_id,
                user_email_id=user_email.id,
                expires_at=challenge.expires_at,
                external_token=SecretStr(material.external_token),
            )
        else:
            if keyring is None:
                raise InvalidEmailVerificationHmacConfiguration(
                    "email verification HMAC keyring is required for code issuance"
                )
            key_version = keyring.active_key_version
            key = keyring.key_for_version(key_version)
            code = generate_human_email_code()
            code_digest = email_verification_code_digest(
                key=key,
                challenge_id=challenge_id,
                user_id=user.id,
                user_email_id=user_email.id,
                code=code,
            )
            challenge = EmailVerificationChallenge(
                id=challenge_id,
                user_email_id=user_email.id,
                material_type=EmailVerificationMaterialType.CODE,
                code_digest=code_digest,
                hmac_key_version=key_version,
                attempt_count=0,
                max_attempts=CODE_CHALLENGE_MAX_ATTEMPTS,
                created_at=decision_time,
                expires_at=decision_time + CODE_CHALLENGE_TTL,
            )
            result = StagedCodeChallenge(
                challenge_id=challenge_id,
                user_email_id=user_email.id,
                expires_at=challenge.expires_at,
                code=SecretStr(code),
            )

        for sibling in live_siblings:
            sibling.invalidated_at = decision_time
            sibling.invalidation_reason = EmailVerificationInvalidationReason.SUPERSEDED
        session.add(challenge)
        session.flush()
        return result
