"""Allow the network_scan action kind (ADR-020).

Revision ID: 0018_network_scan_action
Revises: 0017_device_events
"""

from alembic import op

revision = "0018_network_scan_action"
down_revision = "0017_device_events"
branch_labels = None
depends_on = None

_OLD = "kind IN ('send_file', 'lock_screen', 'webcam_photo')"
_NEW = "kind IN ('send_file', 'lock_screen', 'webcam_photo', 'network_scan')"


def _swap(check: str) -> None:
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint("ck_device_commands_kind", "device_commands", check)


def upgrade() -> None:
    _swap(_NEW)


def downgrade() -> None:
    # Safe only if no network_scan rows remain; drop them first so the old check holds.
    op.execute("DELETE FROM device_commands WHERE kind = 'network_scan'")
    _swap(_OLD)
