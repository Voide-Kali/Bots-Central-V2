# ruff: noqa: E501
"""Create the email-verification challenge persistence foundation.

Revision ID: 0003_email_challenge_foundation
Revises: 0002_auth_database_foundation
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_email_challenge_foundation"
down_revision = "0002_auth_database_foundation"
branch_labels = None
depends_on = None


email_verification_material_type = postgresql.ENUM(
    "link", "code", name="email_verification_material_type", create_type=False
)
email_verification_invalidation_reason = postgresql.ENUM(
    "superseded",
    "attempts_exhausted",
    "account_state_changed",
    "email_already_verified",
    "key_compromised",
    name="email_verification_invalidation_reason",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    email_verification_material_type.create(bind, checkfirst=False)
    email_verification_invalidation_reason.create(bind, checkfirst=False)

    op.create_table(
        "email_verification_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_email_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_type", email_verification_material_type, nullable=False),
        sa.Column("link_token_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("code_digest", sa.LargeBinary(length=32), nullable=True),
        sa.Column("hmac_key_version", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", email_verification_invalidation_reason, nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_email_verification_expires_after_created"),
        sa.CheckConstraint(
            "NOT (consumed_at IS NOT NULL AND invalidated_at IS NOT NULL)",
            name="ck_email_verification_terminal_states_exclusive",
        ),
        sa.CheckConstraint(
            "(invalidated_at IS NULL AND invalidation_reason IS NULL) "
            "OR (invalidated_at IS NOT NULL AND invalidation_reason IS NOT NULL)",
            name="ck_email_verification_invalidation_state",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(["user_email_id"], ["user_emails.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_email_verification_link_token_digest",
        "email_verification_challenges",
        ["link_token_digest"],
        unique=True,
        postgresql_where=sa.text("link_token_digest IS NOT NULL"),
    )
    op.create_index(
        "ix_email_verification_challenges_user_email_id",
        "email_verification_challenges",
        ["user_email_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_verification_challenges_user_email_created_at",
        "email_verification_challenges",
        ["user_email_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_challenges_user_email_created_at",
        table_name="email_verification_challenges",
    )
    op.drop_index(
        "ix_email_verification_challenges_user_email_id",
        table_name="email_verification_challenges",
    )
    op.drop_index(
        "uq_email_verification_link_token_digest",
        table_name="email_verification_challenges",
    )
    op.drop_table("email_verification_challenges")

    bind = op.get_bind()
    email_verification_invalidation_reason.drop(bind, checkfirst=False)
    email_verification_material_type.drop(bind, checkfirst=False)
