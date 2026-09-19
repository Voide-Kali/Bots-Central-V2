"""Add durable cancellation state for unconsumed device pairings.

Revision ID: 0007_pairing_revocation
Revises: 0006_device_online_v01
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_pairing_revocation"
down_revision = "0006_device_online_v01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_pairing_tokens", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_device_pairing_not_revoked_and_consumed",
        "device_pairing_tokens",
        "revoked_at IS NULL OR consumed_at IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_device_pairing_not_revoked_and_consumed", "device_pairing_tokens", type_="check"
    )
    op.drop_column("device_pairing_tokens", "revoked_at")
