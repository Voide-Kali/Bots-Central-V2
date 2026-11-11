"""HKDF flag-day: invalidate PINs hashed with legacy key (ADR-038).

HKDF key derivation changes the subkey used for action-PIN MACs.  All existing
``pin_mac`` values are therefore invalid.  This migration:

1. Adds ``key_version`` (default 2 = HKDF) so future rotations are trackable.
2. Deletes existing rows — the owner re-creates the PIN once at next use.
3. Cancels any open command approvals (ephemeral; they expire in minutes anyway).

Revision ID: 0024_hkdf_flag_day
Revises: 0023_power_action
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_hkdf_flag_day"
down_revision = "0023_power_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Track key version on durable MAC rows.
    op.add_column(
        "action_pins",
        sa.Column(
            "key_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="2",
        ),
    )
    # 2. Flag-day: wipe PINs hashed with the old (v1) key.  The owner sets a
    #    new PIN on next use; it will be stored with key_version=2 (HKDF).
    op.execute("DELETE FROM action_pins")
    # 3. Ephemeral codes (password-reset, command-approval) will simply fail on
    #    the next attempt and be re-issued; no migration needed.


def downgrade() -> None:
    op.drop_column("action_pins", "key_version")
