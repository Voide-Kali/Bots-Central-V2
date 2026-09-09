"""Application-owned transactions for email-verification domain operations."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.email_verification_consume import (
    EmailVerificationConsumeOutcome,
    consume_email_verification_code,
    consume_email_verification_link,
)
from app.auth.email_verification_delivery import DeliveryIntent
from app.auth.email_verification_issuance import (
    EmailVerificationIssuanceOutcome,
    StagedCodeChallenge,
    StagedLinkChallenge,
    stage_email_verification,
)
from app.auth.email_verification_materials import EmailVerificationHmacKeyring
from app.auth.emails import validate_and_canonicalize_email
from app.auth.registration import DuplicateEmailError, register_user
from app.db.enums import EmailVerificationMaterialType
from app.db.models import UserEmail

SessionFactory = Callable[[], Session]


class EmailVerificationApplicationInvariantError(RuntimeError):
    """Raised when persisted rows violate the application composition contract."""


@dataclass(frozen=True)
class RegistrationAccepted:
    """Sanitized future-transport outcome, independent of duplicate registration."""


@dataclass(frozen=True)
class RegistrationApplicationResult:
    public_outcome: RegistrationAccepted
    delivery_intent: DeliveryIntent | None = field(repr=False)


@dataclass(frozen=True)
class ResendAccepted:
    """Sanitized future-transport outcome, independent of account/challenge state."""


@dataclass(frozen=True)
class ResendApplicationResult:
    public_outcome: ResendAccepted
    delivery_intent: DeliveryIntent | None = field(repr=False)


@dataclass(frozen=True)
class ConsumeApplicationResult:
    """Returned only after the owned outer transaction has ended normally."""

    outcome: EmailVerificationConsumeOutcome


def _delivery_intent(
    *, recipient: str, outcome: EmailVerificationIssuanceOutcome
) -> DeliveryIntent | None:
    if isinstance(outcome, StagedLinkChallenge):
        return DeliveryIntent(
            recipient=recipient,
            challenge_id=outcome.challenge_id,
            expires_at=outcome.expires_at,
            material_type=EmailVerificationMaterialType.LINK,
            material=outcome.external_token,
        )
    if isinstance(outcome, StagedCodeChallenge):
        return DeliveryIntent(
            recipient=recipient,
            challenge_id=outcome.challenge_id,
            expires_at=outcome.expires_at,
            material_type=EmailVerificationMaterialType.CODE,
            material=outcome.code,
        )
    return None


def _exact_primary_email(session: Session, user_id: uuid.UUID) -> UserEmail:
    emails = list(
        session.scalars(
            select(UserEmail).where(UserEmail.user_id == user_id, UserEmail.is_primary.is_(True))
        )
    )
    if len(emails) != 1:
        raise EmailVerificationApplicationInvariantError(
            "registered user must have exactly one primary email"
        )
    return emails[0]


def register_and_stage_email_verification(
    session_factory: SessionFactory,
    *,
    email: str,
    password: str,
    material_type: EmailVerificationMaterialType,
    keyring: EmailVerificationHmacKeyring | None = None,
) -> RegistrationApplicationResult:
    """Atomically register and stage, then expose an intent only after outer commit."""
    delivery_intent: DeliveryIntent | None = None
    with session_factory() as session:
        with session.begin():
            try:
                registration = register_user(session, email=email, password=password)
            except DuplicateEmailError:
                pass
            else:
                user_email = _exact_primary_email(session, registration.user_id)
                staged = stage_email_verification(
                    session,
                    user_email_id=user_email.id,
                    material_type=material_type,
                    keyring=keyring,
                )
                if not isinstance(staged, StagedLinkChallenge | StagedCodeChallenge):
                    raise EmailVerificationApplicationInvariantError(
                        "newly registered user must receive an email verification challenge"
                    )
                delivery_intent = _delivery_intent(
                    recipient=user_email.email_display, outcome=staged
                )
    return RegistrationApplicationResult(
        public_outcome=RegistrationAccepted(), delivery_intent=delivery_intent
    )


def resend_email_verification(
    session_factory: SessionFactory,
    *,
    email: str,
    material_type: EmailVerificationMaterialType,
    keyring: EmailVerificationHmacKeyring | None = None,
) -> ResendApplicationResult:
    """Stage a resend and expose post-commit plaintext only for a staged challenge."""
    delivery_intent: DeliveryIntent | None = None
    canonical_email = validate_and_canonicalize_email(email)
    with session_factory() as session:
        with session.begin():
            user_email = session.scalar(
                select(UserEmail).where(UserEmail.email_canonical == canonical_email.canonical)
            )
            if user_email is not None:
                staged = stage_email_verification(
                    session,
                    user_email_id=user_email.id,
                    material_type=material_type,
                    keyring=keyring,
                )
                delivery_intent = _delivery_intent(
                    recipient=user_email.email_display, outcome=staged
                )
    return ResendApplicationResult(public_outcome=ResendAccepted(), delivery_intent=delivery_intent)


def consume_email_verification_code_application(
    session_factory: SessionFactory,
    *,
    challenge_id: uuid.UUID,
    code: str,
    keyring: EmailVerificationHmacKeyring,
) -> ConsumeApplicationResult:
    """Commit every normal consume outcome before exposing it to future transport."""
    with session_factory() as session:
        with session.begin():
            outcome = consume_email_verification_code(
                session, challenge_id=challenge_id, code=code, keyring=keyring
            )
    return ConsumeApplicationResult(outcome=outcome)


def consume_email_verification_link_application(
    session_factory: SessionFactory, *, external_token: str
) -> ConsumeApplicationResult:
    """Commit every normal LINK consume outcome before exposing it to future transport."""
    with session_factory() as session:
        with session.begin():
            outcome = consume_email_verification_link(session, external_token=external_token)
    return ConsumeApplicationResult(outcome=outcome)
