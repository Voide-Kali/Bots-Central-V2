import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.db.enums import (
    AccountStatus,
    AuthenticationLevel,
    DeviceLifecycleStatus,
    EmailVerificationInvalidationReason,
    EmailVerificationMaterialType,
    SessionRevocationReason,
    persisted_enum_values,
)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("name <> ''", name="ck_devices_name_not_empty"),
        CheckConstraint("platform <> ''", name="ck_devices_platform_not_empty"),
        CheckConstraint(
            "public_key IS NULL OR octet_length(public_key) = 32",
            name="ck_devices_public_key_length",
        ),
        CheckConstraint(
            "last_heartbeat_seq IS NULL OR (last_heartbeat_seq >= 0 "
            "AND last_heartbeat_seq <= 18446744073709551615)",
            name="ck_devices_heartbeat_sequence_uint64",
        ),
        Index("ix_devices_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[DeviceLifecycleStatus] = mapped_column(
        Enum(
            DeviceLifecycleStatus,
            name="device_lifecycle_status",
            values_callable=persisted_enum_values,
        ),
        nullable=False,
        default=DeviceLifecycleStatus.PENDING,
        server_default=DeviceLifecycleStatus.PENDING.value,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    public_key_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_heartbeat_seq: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"Device(id={self.id!s}, user_id={self.user_id!s}, "
            f"lifecycle_status={self.lifecycle_status.value!r})"
        )


class DevicePairingToken(Base):
    __tablename__ = "device_pairing_tokens"
    __table_args__ = (
        CheckConstraint("octet_length(token_digest) = 32", name="ck_device_pairing_token_digest"),
        CheckConstraint("expires_at > created_at", name="ck_device_pairing_expires_after_created"),
        CheckConstraint(
            "(consumed_at IS NULL AND device_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND device_id IS NOT NULL)",
            name="ck_device_pairing_consumption_state",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR consumed_at IS NULL",
            name="ck_device_pairing_not_revoked_and_consumed",
        ),
        Index("ix_device_pairing_tokens_expires_at", "expires_at"),
        Index("ix_device_pairing_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    initiating_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=True
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


class EmailVerificationChallenge(Base):
    __tablename__ = "email_verification_challenges"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at", name="ck_email_verification_expires_after_created"
        ),
        CheckConstraint(
            "NOT (consumed_at IS NOT NULL AND invalidated_at IS NOT NULL)",
            name="ck_email_verification_terminal_states_exclusive",
        ),
        CheckConstraint(
            "(invalidated_at IS NULL AND invalidation_reason IS NULL) "
            "OR (invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)",
            name="ck_email_verification_invalidation_state",
        ),
        CheckConstraint(
            "(material_type = 'link' "
            "AND link_token_digest IS NOT NULL "
            "AND octet_length(link_token_digest) = 32 "
            "AND code_digest IS NULL "
            "AND hmac_key_version IS NULL "
            "AND attempt_count IS NULL "
            "AND max_attempts IS NULL) "
            "OR (material_type = 'code' "
            "AND link_token_digest IS NULL "
            "AND code_digest IS NOT NULL "
            "AND octet_length(code_digest) = 32 "
            "AND hmac_key_version IS NOT NULL "
            "AND hmac_key_version <> '' "
            "AND max_attempts IS NOT NULL "
            "AND max_attempts = 5 "
            "AND attempt_count IS NOT NULL "
            "AND attempt_count >= 0 "
            "AND attempt_count <= 5)",
            name="ck_email_verification_material_fields",
        ),
        Index(
            "uq_email_verification_link_token_digest",
            "link_token_digest",
            unique=True,
            postgresql_where=text("link_token_digest IS NOT NULL"),
        ),
        Index("ix_email_verification_challenges_user_email_id", "user_email_id"),
        Index(
            "ix_email_verification_challenges_user_email_created_at",
            "user_email_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_emails.id", ondelete="RESTRICT"),
        nullable=False,
    )
    material_type: Mapped[EmailVerificationMaterialType] = mapped_column(
        Enum(
            EmailVerificationMaterialType,
            name="email_verification_material_type",
            values_callable=persisted_enum_values,
        ),
        nullable=False,
    )
    link_token_digest: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    code_digest: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    hmac_key_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[EmailVerificationInvalidationReason | None] = mapped_column(
        Enum(
            EmailVerificationInvalidationReason,
            name="email_verification_invalidation_reason",
            values_callable=persisted_enum_values,
        ),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            "EmailVerificationChallenge("
            f"id={self.id!s}, user_email_id={self.user_email_id!s}, "
            f"material_type={self.material_type.value!r}, "
            f"consumed={self.consumed_at is not None!r}, "
            f"invalidated={self.invalidated_at is not None!r})"
        )


class AuthAbuseBucket(Base):
    """Shared, pseudonymized fixed-window counter for anonymous auth admission."""

    __tablename__ = "auth_abuse_buckets"
    __table_args__ = (
        CheckConstraint("operation <> ''", name="ck_auth_abuse_buckets_operation_not_empty"),
        CheckConstraint("dimension <> ''", name="ck_auth_abuse_buckets_dimension_not_empty"),
        CheckConstraint("octet_length(bucket_key) = 32", name="ck_auth_abuse_buckets_key_length"),
        CheckConstraint("count >= 1", name="ck_auth_abuse_buckets_count_positive"),
        CheckConstraint(
            "expires_at > window_started_at", name="ck_auth_abuse_buckets_expiry_after_start"
        ),
        Index("ix_auth_abuse_buckets_expires_at", "expires_at"),
    )

    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(16), primary_key=True)
    bucket_key: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            "AuthAbuseBucket("
            f"operation={self.operation!r}, dimension={self.dimension!r}, "
            f"count={self.count!r})"
        )


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


class DeviceTelemetrySample(Base):
    """One bounded system-metrics sample accepted with a signed heartbeat."""

    __tablename__ = "device_telemetry_samples"
    __table_args__ = (
        CheckConstraint(
            "cpu_percent IS NULL OR (cpu_percent >= 0 AND cpu_percent <= 100)",
            name="ck_device_telemetry_cpu_percent",
        ),
        CheckConstraint("load1 IS NULL OR load1 >= 0", name="ck_device_telemetry_load1"),
        CheckConstraint("cpu_count IS NULL OR cpu_count > 0", name="ck_device_telemetry_cpu_count"),
        CheckConstraint(
            "memory_used_bytes IS NULL OR memory_total_bytes IS NULL "
            "OR (memory_used_bytes >= 0 AND memory_used_bytes <= memory_total_bytes)",
            name="ck_device_telemetry_memory",
        ),
        CheckConstraint(
            "disk_used_bytes IS NULL OR disk_total_bytes IS NULL "
            "OR (disk_used_bytes >= 0 AND disk_used_bytes <= disk_total_bytes)",
            name="ck_device_telemetry_disk",
        ),
        CheckConstraint(
            "temperature_c IS NULL OR (temperature_c >= -50 AND temperature_c <= 150)",
            name="ck_device_telemetry_temperature",
        ),
        CheckConstraint(
            "uptime_seconds IS NULL OR uptime_seconds >= 0", name="ck_device_telemetry_uptime"
        ),
        Index("ix_device_telemetry_device_recorded", "device_id", text("recorded_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    load1: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memory_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class TelegramLink(Base):
    """One private Telegram chat bound to one platform user (ADR-011)."""

    __tablename__ = "telegram_links"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_telegram_links_user_id"),
        UniqueConstraint("chat_id", name="uq_telegram_links_chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TelegramLinkCode(Base):
    """Short-lived one-time code; only its SHA-256 digest is stored."""

    __tablename__ = "telegram_link_codes"
    __table_args__ = (
        CheckConstraint(
            "octet_length(code_digest) = 32", name="ck_telegram_link_codes_digest_length"
        ),
        CheckConstraint("expires_at > created_at", name="ck_telegram_link_codes_expiry"),
        Index("ix_telegram_link_codes_user_id", "user_id"),
        UniqueConstraint("code_digest", name="uq_telegram_link_codes_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DevicePresenceAlert(Base):
    """Last presence value already announced to the owner, to alert only on changes."""

    __tablename__ = "device_presence_alerts"
    __table_args__ = (
        CheckConstraint(
            "last_presence IN ('online', 'offline')", name="ck_device_presence_alerts_value"
        ),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    last_presence: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    """Append-only audit row (a database trigger rejects updates and deletes)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor IN ('user', 'device', 'telegram', 'system')", name="ck_audit_events_actor"
        ),
        CheckConstraint(
            "outcome IN ('success', 'denied', 'failure')", name="ck_audit_events_outcome"
        ),
        CheckConstraint("action <> ''", name="ck_audit_events_action_not_empty"),
        Index("ix_audit_events_user_occurred", "user_id", text("occurred_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

class PasswordResetCode(Base):
    """One-time 8-digit reset code; only its keyed HMAC is stored (ADR-014)."""

    __tablename__ = "password_reset_codes"
    __table_args__ = (
        CheckConstraint("octet_length(code_mac) = 32", name="ck_password_reset_mac_length"),
        CheckConstraint("expires_at > created_at", name="ck_password_reset_expiry"),
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_password_reset_attempts"),
        Index("ix_password_reset_codes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_mac: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
