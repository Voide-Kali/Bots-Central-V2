"""Add human-approved device commands and their file payloads (ADR-015).

Revision ID: 0012_device_commands
Revises: 0011_password_reset
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_device_commands"
down_revision = "0011_password_reset"
branch_labels = None
depends_on = None

STATUSES = (
    "'pending_approval', 'approved', 'dispatched', 'completed', 'failed', "
    "'denied', 'expired', 'delivered'"
)


def upgrade() -> None:
    op.create_table(
        "device_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("approval_mac", sa.LargeBinary(length=32), nullable=True),
        sa.Column("approval_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('send_file')", name="ck_device_commands_kind"),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_device_commands_status"),
        sa.CheckConstraint(
            "approval_attempts >= 0 AND approval_attempts <= 5",
            name="ck_device_commands_attempts",
        ),
        sa.CheckConstraint(
            "approval_mac IS NULL OR octet_length(approval_mac) = 32",
            name="ck_device_commands_mac_length",
        ),
    )
    op.create_index("ix_device_commands_device_status", "device_commands", ["device_id", "status"])
    op.create_index("ix_device_commands_user_created", "device_commands", ["user_id", "created_at"])
    op.create_table(
        "command_payloads",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["device_commands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("command_id"),
        sa.CheckConstraint(
            "size_bytes >= 0 AND size_bytes = octet_length(content)",
            name="ck_command_payloads_size",
        ),
        sa.CheckConstraint("octet_length(sha256) = 32", name="ck_command_payloads_sha_length"),
    )


def downgrade() -> None:
    op.drop_table("command_payloads")
    op.drop_index("ix_device_commands_user_created", table_name="device_commands")
    op.drop_index("ix_device_commands_device_status", table_name="device_commands")
    op.drop_table("device_commands")
