"""Opaque IDs of e-mails already announced (ADR-024). No e-mail content is stored.

Revision ID: 0020_email_seen
Revises: 0019_device_battery
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020_email_seen"
down_revision = "0019_device_battery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_seen",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account", sa.String(length=320), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "account", "message_id", name="uq_email_seen_message"),
    )
    op.create_index("ix_email_seen_created", "email_seen", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_seen_created", table_name="email_seen")
    op.drop_table("email_seen")
