"""Add battery level and charging flag to device telemetry samples.

Revision ID: 0019_device_battery
Revises: 0018_network_scan_action
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_device_battery"
down_revision = "0018_network_scan_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_telemetry_samples",
        sa.Column("battery_percent", sa.Integer(), nullable=True),
    )
    op.add_column(
        "device_telemetry_samples",
        sa.Column("battery_charging", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        "ck_device_telemetry_battery_percent",
        "device_telemetry_samples",
        "battery_percent IS NULL OR (battery_percent >= 0 AND battery_percent <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_device_telemetry_battery_percent", "device_telemetry_samples", type_="check"
    )
    op.drop_column("device_telemetry_samples", "battery_charging")
    op.drop_column("device_telemetry_samples", "battery_percent")
