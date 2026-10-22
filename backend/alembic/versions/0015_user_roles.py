"""User roles: user / admin (ADR-017).

Revision ID: 0015_user_roles
Revises: 0014_action_pins
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_user_roles"
down_revision = "0014_action_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("role", sa.String(length=16), server_default="user", nullable=False)
    )
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin')")


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
