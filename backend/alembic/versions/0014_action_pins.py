"""Personal 6-digit PIN that approves actions in Telegram (ADR-016 addendum).

Revision ID: 0014_action_pins
Revises: 0013_action_kinds
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_action_pins"
down_revision = "0013_action_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_pins",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pin_mac", sa.LargeBinary(length=32), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(pin_mac) = 32", name="ck_action_pins_mac_length"),
        sa.CheckConstraint("failed_attempts >= 0", name="ck_action_pins_attempts"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("action_pins")
