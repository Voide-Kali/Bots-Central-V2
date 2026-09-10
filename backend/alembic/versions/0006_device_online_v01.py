"""Add device-online enrollment credentials and replay state.

Revision ID: 0006_device_online_v01
Revises: 0005_device_foundation
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_device_online_v01"
down_revision = "0005_device_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("public_key", sa.LargeBinary(length=32), nullable=True))
    op.add_column(
        "devices", sa.Column("public_key_fingerprint", sa.String(length=64), nullable=True)
    )
    op.add_column("devices", sa.Column("last_heartbeat_seq", sa.Numeric(20, 0), nullable=True))
    op.add_column("devices", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_devices_public_key_length",
        "devices",
        "public_key IS NULL OR octet_length(public_key) = 32",
    )
    op.create_check_constraint(
        "ck_devices_heartbeat_sequence_uint64",
        "devices",
        "last_heartbeat_seq IS NULL OR (last_heartbeat_seq >= 0 "
        "AND last_heartbeat_seq <= 18446744073709551615)",
    )
    op.create_table(
        "device_pairing_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiating_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(token_digest) = 32", name="ck_device_pairing_token_digest"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_device_pairing_expires_after_created"
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL AND device_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND device_id IS NOT NULL)",
            name="ck_device_pairing_consumption_state",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initiating_session_id"], ["sessions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_device_pairing_tokens_expires_at", "device_pairing_tokens", ["expires_at"])
    op.create_index("ix_device_pairing_tokens_user_id", "device_pairing_tokens", ["user_id"])
    op.execute(
        """
        CREATE FUNCTION prevent_devices_public_key_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.public_key IS NOT NULL AND NEW.public_key IS DISTINCT FROM OLD.public_key THEN
                RAISE EXCEPTION 'device public key is immutable';
            END IF;
            IF OLD.public_key_fingerprint IS NOT NULL
               AND NEW.public_key_fingerprint IS DISTINCT FROM OLD.public_key_fingerprint THEN
                RAISE EXCEPTION 'device public key fingerprint is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_devices_public_key_immutable
        BEFORE UPDATE ON devices FOR EACH ROW
        EXECUTE FUNCTION prevent_devices_public_key_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_devices_public_key_immutable ON devices")
    op.execute("DROP FUNCTION prevent_devices_public_key_mutation()")
    op.drop_index("ix_device_pairing_tokens_user_id", table_name="device_pairing_tokens")
    op.drop_index("ix_device_pairing_tokens_expires_at", table_name="device_pairing_tokens")
    op.drop_table("device_pairing_tokens")
    op.drop_constraint("ck_devices_heartbeat_sequence_uint64", "devices", type_="check")
    op.drop_constraint("ck_devices_public_key_length", "devices", type_="check")
    op.drop_column("devices", "approved_at")
    op.drop_column("devices", "last_heartbeat_seq")
    op.drop_column("devices", "public_key_fingerprint")
    op.drop_column("devices", "public_key")
