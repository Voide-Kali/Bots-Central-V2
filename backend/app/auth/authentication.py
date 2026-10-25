"""PostgreSQL-authoritative server sessions and opaque-token lifecycle."""

import base64
import hashlib
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.audit import events as audit
from app.auth.emails import validate_and_canonicalize_email
from app.auth.passwords import hash_password, verify_password
from app.db.enums import AccountStatus, AuthenticationLevel, SessionRevocationReason
from app.db.models import (
    AccessToken,
    PasswordCredential,
    RefreshToken,
    User,
    UserEmail,
)
from app.db.models import Session as DbSession

SessionFactory = Callable[[], OrmSession]
ACCESS_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=30)
# Idle timeout (ADR-025): one hour without activity logs the person out. Each refresh while
# active slides this window forward; after an hour with no request the session and its refresh
# token both idle-expire, so the next call fails and a fresh login is required.
IDLE_TTL = timedelta(hours=1)
TOKEN_BYTES = 32


class InvalidCredentials(Exception):
    """Publicly indistinguishable failed password authentication."""


class InvalidAccessToken(Exception):
    """The opaque bearer token does not authenticate a usable session."""


@dataclass(frozen=True)
class LoginResult:
    user_id: uuid.UUID
    session_id: uuid.UUID
    access_token: SecretStr
    refresh_token: SecretStr
    access_expires_in: int


@dataclass(frozen=True)
class RefreshResult:
    success: bool
    access_token: SecretStr | None = None
    refresh_token: SecretStr | None = None
    access_expires_in: int | None = None
    reuse_detected: bool = False


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    role: str = "user"


# Calculated at process initialization: unknown-login requests perform one verify,
# rather than making the first request do a hash plus a verify. The value is non-secret.
_DUMMY_PASSWORD_HASH = hash_password("mvp1-dummy-password-never-accepted")


def _token() -> tuple[str, bytes]:
    raw = secrets.token_bytes(TOKEN_BYTES)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), hashlib.sha256(raw).digest()


def _digest_token(value: str) -> bytes:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    if len(value) != 43 or any(character not in alphabet for character in value):
        raise ValueError("invalid opaque token")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (ValueError, UnicodeEncodeError) as error:
        raise ValueError("invalid opaque token") from error
    if (
        len(raw) != TOKEN_BYTES
        or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != value
    ):
        raise ValueError("invalid opaque token")
    return hashlib.sha256(raw).digest()


def _clock(session: OrmSession) -> datetime:
    return cast(datetime, session.scalar(text("SELECT clock_timestamp()")))


def _seconds_until(now: datetime, expiry: datetime) -> int:
    return max(0, int((expiry - now).total_seconds()))


def _load_locked_session_context(
    session: OrmSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> tuple[User, DbSession] | None:
    """Authoritative lock order is User → Session → RefreshToken → AccessToken."""
    user = session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        return None
    db_session = session.scalar(
        select(DbSession)
        .where(DbSession.id == session_id, DbSession.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (user, db_session) if db_session is not None else None


def _session_usable(user: User, db_session: DbSession, now: datetime) -> bool:
    return (
        user.status is AccountStatus.ACTIVE
        and user.security_version == db_session.security_version
        and db_session.revoked_at is None
        and db_session.expires_at > now
        and db_session.idle_expires_at > now
    )


def _revoke_session_and_tokens(
    session: OrmSession,
    db_session: DbSession,
    now: datetime,
    reason: SessionRevocationReason,
) -> None:
    """Lock all token rows after User and Session; revocation is server authoritative."""
    refreshes = session.scalars(
        select(RefreshToken)
        .where(RefreshToken.session_id == db_session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    accesses = session.scalars(
        select(AccessToken)
        .where(AccessToken.session_id == db_session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if db_session.revoked_at is None:
        db_session.revoked_at = now
        db_session.revocation_reason = reason
    for refresh_token in refreshes:
        if refresh_token.revoked_at is None:
            refresh_token.revoked_at = now
    for access_token in accesses:
        if access_token.revoked_at is None:
            access_token.revoked_at = now


def login(session_factory: SessionFactory, *, email: str, password: str) -> LoginResult:
    canonical = validate_and_canonicalize_email(email).canonical
    with session_factory() as session, session.begin():
        locator = session.execute(
            select(User.id.label("user_id"), UserEmail.id.label("email_id"))
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_canonical == canonical, UserEmail.is_primary.is_(True))
        ).one_or_none()
        if locator is None:
            verify_password(_DUMMY_PASSWORD_HASH, password)
            raise InvalidCredentials
        user = session.scalar(
            select(User)
            .where(User.id == locator.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        email_row = session.scalar(
            select(UserEmail)
            .where(UserEmail.id == locator.email_id, UserEmail.user_id == locator.user_id)
            .execution_options(populate_existing=True)
        )
        credential = session.scalar(
            select(PasswordCredential)
            .where(PasswordCredential.user_id == locator.user_id)
            .execution_options(populate_existing=True)
        )
        if user is None or email_row is None or credential is None:
            verify_password(_DUMMY_PASSWORD_HASH, password)
            raise InvalidCredentials
        valid_password = verify_password(credential.password_hash, password)
        if not valid_password or user.status is not AccountStatus.ACTIVE:
            raise InvalidCredentials
        now = _clock(session)
        session_id = uuid.uuid4()
        access_plain, access_digest = _token()
        refresh_plain, refresh_digest = _token()
        absolute_expiry = now + SESSION_TTL
        idle_expiry = min(now + IDLE_TTL, absolute_expiry)
        access_expiry = min(now + ACCESS_TTL, idle_expiry, absolute_expiry)
        db_session = DbSession(
            id=session_id,
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=absolute_expiry,
            idle_expires_at=idle_expiry,
            security_version=user.security_version,
            authentication_level=AuthenticationLevel.PASSWORD_AUTHENTICATED,
            authentication_methods=["password"],
        )
        session.add(db_session)
        # PostgreSQL enforces the token foreign keys immediately. This remains
        # within the caller-owned transaction: a later token failure rolls back
        # this inserted session together with the whole login operation.
        session.flush()
        session.add(
            AccessToken(
                session_id=session_id,
                token_digest=access_digest,
                created_at=now,
                expires_at=access_expiry,
            )
        )
        session.add(
            RefreshToken(
                session_id=session_id,
                family_id=session_id,
                token_digest=refresh_digest,
                generation=1,
                created_at=now,
                expires_at=idle_expiry,
            )
        )
        audit.record(
            session,
            user_id=user.id,
            action="auth.login",
            actor="user",
            target_type="session",
            target_id=str(session_id),
        )
        return LoginResult(
            user.id,
            session_id,
            SecretStr(access_plain),
            SecretStr(refresh_plain),
            _seconds_until(now, access_expiry),
        )


def authenticate_access(session_factory: SessionFactory, token: str) -> AuthenticatedPrincipal:
    try:
        digest = _digest_token(token)
    except ValueError as error:
        raise InvalidAccessToken from error
    with session_factory() as session, session.begin():
        locator = session.execute(
            select(AccessToken.id.label("access_id"), AccessToken.session_id, DbSession.user_id)
            .join(DbSession, DbSession.id == AccessToken.session_id)
            .where(AccessToken.token_digest == digest)
        ).one_or_none()
        if locator is None:
            raise InvalidAccessToken
        context = _load_locked_session_context(
            session, user_id=locator.user_id, session_id=locator.session_id
        )
        if context is None:
            raise InvalidAccessToken
        user, db_session = context
        access = session.scalar(
            select(AccessToken)
            .where(
                AccessToken.id == locator.access_id,
                AccessToken.session_id == db_session.id,
                AccessToken.token_digest == digest,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        email = session.scalar(
            select(UserEmail)
            .where(UserEmail.user_id == user.id, UserEmail.is_primary.is_(True))
            .execution_options(populate_existing=True)
        )
        now = _clock(session)
        if (
            access is None
            or email is None
            or access.revoked_at is not None
            or access.expires_at <= now
            or not _session_usable(user, db_session, now)
        ):
            raise InvalidAccessToken
        db_session.last_seen_at = now
        db_session.idle_expires_at = min(now + IDLE_TTL, db_session.expires_at)
        return AuthenticatedPrincipal(user.id, db_session.id, email.email_canonical, user.role)


def refresh(session_factory: SessionFactory, token: str) -> RefreshResult:
    try:
        digest = _digest_token(token)
    except ValueError:
        return RefreshResult(False)
    with session_factory() as session, session.begin():
        locator = session.execute(
            select(RefreshToken.id.label("refresh_id"), RefreshToken.session_id, DbSession.user_id)
            .join(DbSession, DbSession.id == RefreshToken.session_id)
            .where(RefreshToken.token_digest == digest)
        ).one_or_none()
        if locator is None:
            return RefreshResult(False)
        context = _load_locked_session_context(
            session, user_id=locator.user_id, session_id=locator.session_id
        )
        if context is None:
            return RefreshResult(False)
        user, db_session = context
        old = session.scalar(
            select(RefreshToken)
            .where(
                RefreshToken.id == locator.refresh_id,
                RefreshToken.session_id == db_session.id,
                RefreshToken.token_digest == digest,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = _clock(session)
        if old is None:
            return RefreshResult(False)
        if old.consumed_at is not None or old.revoked_at is not None:
            _revoke_session_and_tokens(
                session,
                db_session,
                now,
                SessionRevocationReason.REFRESH_REUSE_DETECTED,
            )
            return RefreshResult(False, reuse_detected=True)
        if old.expires_at <= now or not _session_usable(user, db_session, now):
            return RefreshResult(False)
        old.consumed_at = now
        access_plain, access_digest = _token()
        refresh_plain, refresh_digest = _token()
        db_session.last_seen_at = now
        db_session.idle_expires_at = min(now + IDLE_TTL, db_session.expires_at)
        access_expiry = min(now + ACCESS_TTL, db_session.idle_expires_at, db_session.expires_at)
        successor = RefreshToken(
            session_id=db_session.id,
            family_id=old.family_id,
            token_digest=refresh_digest,
            generation=old.generation + 1,
            created_at=now,
            expires_at=db_session.idle_expires_at,
        )
        session.add(successor)
        session.flush()
        old.replaced_by_id = successor.id
        session.add(
            AccessToken(
                session_id=db_session.id,
                token_digest=access_digest,
                created_at=now,
                expires_at=access_expiry,
            )
        )
        return RefreshResult(
            True,
            SecretStr(access_plain),
            SecretStr(refresh_plain),
            _seconds_until(now, access_expiry),
        )


def logout(session_factory: SessionFactory, token: str) -> None:
    """Idempotently revoke a session and every linked access/refresh token."""
    try:
        digest = _digest_token(token)
    except ValueError:
        return
    with session_factory() as session, session.begin():
        locator = session.execute(
            select(AccessToken.session_id, DbSession.user_id)
            .join(DbSession, DbSession.id == AccessToken.session_id)
            .where(AccessToken.token_digest == digest)
        ).one_or_none()
        if locator is None:
            return
        context = _load_locked_session_context(
            session, user_id=locator.user_id, session_id=locator.session_id
        )
        if context is None:
            return
        _, db_session = context
        _revoke_session_and_tokens(
            session, db_session, _clock(session), SessionRevocationReason.LOGOUT
        )


def logout_refresh(session_factory: SessionFactory, token: str) -> bool:
    """Idempotently revoke the owning session from a refresh-cookie digest.

    Unknown material deliberately has no effect.  A consumed refresh is still a
    known member of its family and therefore safely identifies only that session.
    """
    try:
        digest = _digest_token(token)
    except ValueError:
        return False
    with session_factory() as session, session.begin():
        locator = session.execute(
            select(RefreshToken.session_id, DbSession.user_id)
            .join(DbSession, DbSession.id == RefreshToken.session_id)
            .where(RefreshToken.token_digest == digest)
        ).one_or_none()
        if locator is None:
            return False
        context = _load_locked_session_context(
            session, user_id=locator.user_id, session_id=locator.session_id
        )
        if context is None:
            return False
        _, db_session = context
        _revoke_session_and_tokens(
            session, db_session, _clock(session), SessionRevocationReason.LOGOUT
        )
        return True
