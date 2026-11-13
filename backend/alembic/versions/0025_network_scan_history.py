"""Network scan history tables.

Revision ID: 0025_network_scan_history
Revises: 0024_hkdf_flag_day
Create Date: 2026-11-11

Persists the parsed output of network_scan actions so the platform can
compare consecutive scans and alert on new hosts.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0025_network_scan_history"
down_revision = "0024_hkdf_flag_day"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "network_scans",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "device_id", UUID(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "command_id", UUID(as_uuid=True),
            sa.ForeignKey("device_commands.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("host_count", sa.Integer, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Index(
            "ix_network_scans_device_scanned", "device_id", "scanned_at",
        ),
    )
    op.create_table(
        "network_scan_hosts",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "scan_id", UUID(as_uuid=True),
            sa.ForeignKey("network_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column(
            "first_seen_scan_id", UUID(as_uuid=True),
            sa.ForeignKey("network_scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Index("ix_network_scan_hosts_scan_id", "scan_id"),
    )


def downgrade() -> None:
    op.drop_table("network_scan_hosts")
    op.drop_table("network_scans")
