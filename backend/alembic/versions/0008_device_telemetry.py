"""Add bounded device telemetry samples carried by signed heartbeats.

Revision ID: 0008_device_telemetry
Revises: 0007_pairing_revocation
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_device_telemetry"
down_revision = "0007_pairing_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_telemetry_samples",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("load1", sa.Float(), nullable=True),
        sa.Column("cpu_count", sa.Integer(), nullable=True),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("memory_used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("disk_used_bytes", sa.BigInteger(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "cpu_percent IS NULL OR (cpu_percent >= 0 AND cpu_percent <= 100)",
            name="ck_device_telemetry_cpu_percent",
        ),
        sa.CheckConstraint("load1 IS NULL OR load1 >= 0", name="ck_device_telemetry_load1"),
        sa.CheckConstraint(
            "cpu_count IS NULL OR cpu_count > 0", name="ck_device_telemetry_cpu_count"
        ),
        sa.CheckConstraint(
            "memory_used_bytes IS NULL OR memory_total_bytes IS NULL "
            "OR (memory_used_bytes >= 0 AND memory_used_bytes <= memory_total_bytes)",
            name="ck_device_telemetry_memory",
        ),
        sa.CheckConstraint(
            "disk_used_bytes IS NULL OR disk_total_bytes IS NULL "
            "OR (disk_used_bytes >= 0 AND disk_used_bytes <= disk_total_bytes)",
            name="ck_device_telemetry_disk",
        ),
        sa.CheckConstraint(
            "temperature_c IS NULL OR (temperature_c >= -50 AND temperature_c <= 150)",
            name="ck_device_telemetry_temperature",
        ),
        sa.CheckConstraint(
            "uptime_seconds IS NULL OR uptime_seconds >= 0", name="ck_device_telemetry_uptime"
        ),
    )
    op.create_index(
        "ix_device_telemetry_device_recorded",
        "device_telemetry_samples",
        ["device_id", sa.text("recorded_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_device_telemetry_device_recorded", table_name="device_telemetry_samples")
    op.drop_table("device_telemetry_samples")
