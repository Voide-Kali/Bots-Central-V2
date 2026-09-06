# ruff: noqa: E501
"""Create the persistent authentication domain foundation.

Revision ID: 0002_auth_database_foundation
Revises: 0001_foundation
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_auth_database_foundation"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


account_status = postgresql.ENUM(
    "pending_verification", "active", "locked", "disabled", name="account_status", create_type=False
)
authentication_level = postgresql.ENUM(
    "password_authenticated", name="authentication_level", create_type=False
)
session_revocation_reason = postgresql.ENUM(
    "logout",
    "user_revoked",
    "password_changed",
    "password_reset",
    "email_changed",
    "account_locked",
    "account_disabled",
    "refresh_reuse_detected",
    "security_containment",
    name="session_revocation_reason",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    account_status.create(bind, checkfirst=False)
    authentication_level.create(bind, checkfirst=False)
    session_revocation_reason.create(bind, checkfirst=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", account_status, server_default="pending_verification", nullable=False),
        sa.Column("security_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("security_version >= 0", name="ck_users_security_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_canonical", sa.String(length=320), nullable=False),
        sa.Column("email_display", sa.String(length=320), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("email_canonical <> ''", name="ck_user_emails_canonical_not_empty"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_canonical"),
    )
    op.create_index("ix_user_emails_user_id", "user_emails", ["user_id"], unique=False)
    op.create_index(
        "uq_user_emails_primary_per_user",
        "user_emails",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    op.create_table(
        "password_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("password_hash", sa.String(length=1024), nullable=False),
        sa.Column("password_hash_version", sa.String(length=64), nullable=False),
        sa.Column(
            "password_hash_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", session_revocation_reason, nullable=True),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column(
            "client_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("authentication_level", authentication_level, server_default="password_authenticated", nullable=False),
        sa.Column(
            "authentication_methods",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("recent_reauthenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_reauthentication_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recent_reauthentication_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("security_version >= 0", name="ck_sessions_security_version"),
        sa.CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
        sa.CheckConstraint("idle_expires_at > created_at", name="ck_sessions_idle_expires_after_created"),
        sa.CheckConstraint("idle_expires_at <= expires_at", name="ck_sessions_idle_within_absolute"),
        sa.CheckConstraint(
            "(recent_reauthenticated_at IS NULL AND recent_reauthentication_expires_at IS NULL) "
            "OR (recent_reauthenticated_at IS NOT NULL "
            "AND recent_reauthentication_expires_at IS NOT NULL "
            "AND recent_reauthentication_expires_at > recent_reauthenticated_at)",
            name="ck_sessions_recent_reauthentication_window",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_table(
        "access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_access_tokens_expires_after_created"),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_access_tokens_digest_length"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_access_tokens_session_id", "access_tokens", ["session_id"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("generation > 0", name="ck_refresh_tokens_generation_positive"),
        sa.CheckConstraint("expires_at > created_at", name="ck_refresh_tokens_expires_after_created"),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_refresh_tokens_digest_length"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"], unique=False)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)
    op.create_index(
        "uq_refresh_tokens_family_generation", "refresh_tokens", ["family_id", "generation"], unique=True
    )
    op.create_index(
        "ix_refresh_tokens_session_family", "refresh_tokens", ["session_id", "family_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_session_family", table_name="refresh_tokens")
    op.drop_index("uq_refresh_tokens_family_generation", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_access_tokens_session_id", table_name="access_tokens")
    op.drop_table("access_tokens")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("password_credentials")
    op.drop_index("uq_user_emails_primary_per_user", table_name="user_emails")
    op.drop_index("ix_user_emails_user_id", table_name="user_emails")
    op.drop_table("user_emails")
    op.drop_table("users")

    bind = op.get_bind()
    session_revocation_reason.drop(bind, checkfirst=False)
    authentication_level.drop(bind, checkfirst=False)
    account_status.drop(bind, checkfirst=False)
