"""Allow the power action kind: shutdown, reboot, suspend (ADR-016).

Revision ID: 0023_power_action
Revises: 0022_device_network_location
"""

from alembic import op

revision = "0023_power_action"
down_revision = "0022_device_network_location"
branch_labels = None
depends_on = None

_OLD = "kind IN ('send_file', 'lock_screen', 'webcam_photo', 'network_scan')"
_NEW = "kind IN ('send_file', 'lock_screen', 'webcam_photo', 'network_scan', 'power')"


def _swap(check: str) -> None:
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint("ck_device_commands_kind", "device_commands", check)


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    # Safe only if no power rows remain; drop them first so the old check holds.
    op.execute("DELETE FROM device_commands WHERE kind = 'power'")
    _swap(_OLD)
