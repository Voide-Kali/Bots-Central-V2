"""Events a computer reports by itself: wrong password with photo (ADR-019).

Revision ID: 0017_device_events
Revises: 0016_device_live
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017_device_events"
down_revision = "0016_device_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("photo", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('failed_login')", name="ck_device_events_kind"),
        sa.CheckConstraint(
            "photo IS NULL OR octet_length(photo) <= 5242880", name="ck_device_events_photo_size"
        ),
    )
    op.create_index("ix_device_events_pending", "device_events", ["delivered_at", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_device_events_pending", table_name="device_events")
    op.drop_table("device_events")
