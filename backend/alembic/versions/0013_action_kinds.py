"""Allow the first ADR-016 actions: lock_screen and webcam_photo.

Revision ID: 0013_action_kinds
Revises: 0012_device_commands
"""

from alembic import op

revision = "0013_action_kinds"
down_revision = "0012_device_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint(
        "ck_device_commands_kind",
        "device_commands",
        "kind IN ('send_file', 'lock_screen', 'webcam_photo')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM device_commands WHERE kind <> 'send_file'")
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint(
        "ck_device_commands_kind", "device_commands", "kind IN ('send_file')"
    )
