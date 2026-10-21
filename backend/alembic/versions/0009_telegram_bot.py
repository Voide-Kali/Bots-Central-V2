"""Add Telegram account links, one-time link codes, and presence alert state.

Revision ID: 0009_telegram_bot
Revises: 0008_device_telemetry
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_telegram_bot"
down_revision = "0008_device_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_telegram_links_user_id"),
        sa.UniqueConstraint("chat_id", name="uq_telegram_links_chat_id"),
    )
    op.create_table(
        "telegram_link_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_digest", name="uq_telegram_link_codes_digest"),
        sa.CheckConstraint(
            "octet_length(code_digest) = 32", name="ck_telegram_link_codes_digest_length"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_telegram_link_codes_expiry"),
    )
    op.create_index("ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"])
    op.create_table(
        "device_presence_alerts",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_presence", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
        sa.CheckConstraint(
            "last_presence IN ('online', 'offline')", name="ck_device_presence_alerts_value"
        ),
    )


def downgrade() -> None:
    op.drop_table("device_presence_alerts")
    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
    op.drop_table("telegram_links")
