"""Add append-only audit events.

Revision ID: 0010_audit_events
Revises: 0009_telegram_bot
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_audit_events"
down_revision = "0009_telegram_bot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "actor IN ('user', 'device', 'telegram', 'system')", name="ck_audit_events_actor"
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'denied', 'failure')", name="ck_audit_events_outcome"
        ),
        sa.CheckConstraint("action <> ''", name="ck_audit_events_action_not_empty"),
    )
    op.create_index(
        "ix_audit_events_user_occurred", "audit_events", ["user_id", sa.text("occurred_at DESC")]
    )
    # Append-only: the application role may insert and read, never rewrite history.
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.user_id IS NULL AND OLD.user_id IS NOT NULL
               AND NEW.occurred_at = OLD.occurred_at AND NEW.action = OLD.action THEN
                RETURN NEW;  -- allowed only for ON DELETE SET NULL of a removed user
            END IF;
            RAISE EXCEPTION 'audit_events is append-only';
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_rewrite BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_rewrite ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.drop_index("ix_audit_events_user_occurred", table_name="audit_events")
    op.drop_table("audit_events")
