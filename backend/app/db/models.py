import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.enums import (
    AccountStatus,
    AuthenticationLevel,
    SessionRevocationReason,
    persisted_enum_values,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("security_version >= 0", name="ck_users_security_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status", values_callable=persisted_enum_values),
        nullable=False,
        default=AccountStatus.PENDING_VERIFICATION,
        server_default=AccountStatus.PENDING_VERIFICATION.value,
    )
    security_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!s}, status={self.status.value!r})"


class UserEmail(Base):
    __tablename__ = "user_emails"
    __table_args__ = (
        CheckConstraint("email_canonical <> ''", name="ck_user_emails_canonical_not_empty"),
        Index(
            "uq_user_emails_primary_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email_canonical: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"UserEmail(id={self.id!s}, user_id={self.user_id!s}, "
            f"is_primary={self.is_primary!r})"
        )


class PasswordCredential(Base):
    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    password_hash: Mapped[str] = mapped_column(String(1024), nullable=False)
    password_hash_version: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"PasswordCredential(user_id={self.user_id!s})"


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("security_version >= 0", name="ck_sessions_security_version"),
        CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
        CheckConstraint(
            "idle_expires_at > created_at", name="ck_sessions_idle_expires_after_created"
        ),
        CheckConstraint("idle_expires_at <= expires_at", name="ck_sessions_idle_within_absolute"),
        CheckConstraint(
            "(recent_reauthenticated_at IS NULL AND recent_reauthentication_expires_at IS NULL) "
            "OR (recent_reauthenticated_at IS NOT NULL "
            "AND recent_reauthentication_expires_at IS NOT NULL "
            "AND recent_reauthentication_expires_at > recent_reauthenticated_at)",
            name="ck_sessions_recent_reauthentication_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[SessionRevocationReason | None] = mapped_column(
        Enum(
            SessionRevocationReason,
            name="session_revocation_reason",
            values_callable=persisted_enum_values,
        ),
        nullable=True,
    )
    security_version: Mapped[int] = mapped_column(Integer, nullable=False)
    client_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    authentication_level: Mapped[AuthenticationLevel] = mapped_column(
        Enum(
            AuthenticationLevel,
            name="authentication_level",
            values_callable=persisted_enum_values,
        ),
        nullable=False,
        default=AuthenticationLevel.PASSWORD_AUTHENTICATED,
        server_default=AuthenticationLevel.PASSWORD_AUTHENTICATED.value,
    )
    authentication_methods: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    recent_reauthenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recent_reauthentication_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    recent_reauthentication_context: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    risk_context: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return (
            f"Session(id={self.id!s}, user_id={self.user_id!s}, "
            f"revoked={self.revoked_at is not None!r})"
        )


class AccessToken(Base):
    __tablename__ = "access_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_access_tokens_expires_after_created"),
        CheckConstraint("octet_length(token_digest) = 32", name="ck_access_tokens_digest_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"AccessToken(id={self.id!s}, session_id={self.session_id!s}, "
            f"revoked={self.revoked_at is not None!r})"
        )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_refresh_tokens_generation_positive"),
        CheckConstraint("expires_at > created_at", name="ck_refresh_tokens_expires_after_created"),
        CheckConstraint("octet_length(token_digest) = 32", name="ck_refresh_tokens_digest_length"),
        Index("uq_refresh_tokens_family_generation", "family_id", "generation", unique=True),
        Index("ix_refresh_tokens_session_family", "session_id", "family_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"RefreshToken(id={self.id!s}, session_id={self.session_id!s}, "
            f"generation={self.generation!r}, consumed={self.consumed_at is not None!r})"
        )
