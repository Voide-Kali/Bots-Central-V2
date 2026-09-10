"""Create device listing foundation.

Revision ID: 0005_device_foundation
Revises: 0004_auth_abuse_control
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_device_foundation"
down_revision = "0004_auth_abuse_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    lifecycle_enum_creator = postgresql.ENUM(
        "pending", "active", "revoked", name="device_lifecycle_status"
    )
    lifecycle_enum_creator.create(op.get_bind())
    lifecycle_enum = postgresql.ENUM(
        "pending",
        "active",
        "revoked",
        name="device_lifecycle_status",
        create_type=False,
    )
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", lifecycle_enum, nullable=False, server_default="pending"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("name <> ''", name="ck_devices_name_not_empty"),
        sa.CheckConstraint("platform <> ''", name="ck_devices_platform_not_empty"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
    postgresql.ENUM(name="device_lifecycle_status").drop(op.get_bind())
