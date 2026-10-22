"""Live telemetry window per device (ADR-018).

Revision ID: 0016_device_live
Revises: 0015_user_roles
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_device_live"
down_revision = "0015_user_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("live_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "live_until")
