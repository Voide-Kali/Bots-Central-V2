"""Add unlock_screen to device_commands kind constraint.

Revision ID: 0025_unlock_screen_action
Revises: 0024_hkdf_flag_day
"""

from alembic import op

revision = "0025_unlock_screen_action"
down_revision = "0024_hkdf_flag_day"


def upgrade() -> None:
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint(
        "ck_device_commands_kind",
        "device_commands",
        (
            "kind IN ("
            "'send_file', 'lock_screen', 'unlock_screen', "
            "'webcam_photo', 'network_scan', 'power')"
        ),
    )


def downgrade() -> None:
    op.drop_constraint("ck_device_commands_kind", "device_commands", type_="check")
    op.create_check_constraint(
        "ck_device_commands_kind",
        "device_commands",
        (
            "kind IN ("
            "'send_file', 'lock_screen', "
            "'webcam_photo', 'network_scan', 'power')"
        ),
    )
