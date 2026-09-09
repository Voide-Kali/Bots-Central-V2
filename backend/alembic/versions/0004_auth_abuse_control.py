"""Create shared anonymous-auth abuse-control buckets.

Revision ID: 0004_auth_abuse_control
Revises: 0003_email_challenge_foundation
Create Date: 2026-09-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_auth_abuse_control"
down_revision = "0003_email_challenge_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_abuse_buckets",
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("bucket_key", sa.LargeBinary(length=32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("operation <> ''", name="ck_auth_abuse_buckets_operation_not_empty"),
        sa.CheckConstraint("dimension <> ''", name="ck_auth_abuse_buckets_dimension_not_empty"),
        sa.CheckConstraint(
            "octet_length(bucket_key) = 32", name="ck_auth_abuse_buckets_key_length"
        ),
        sa.CheckConstraint("count >= 1", name="ck_auth_abuse_buckets_count_positive"),
        sa.CheckConstraint(
            "expires_at > window_started_at", name="ck_auth_abuse_buckets_expiry_after_start"
        ),
        sa.PrimaryKeyConstraint("operation", "dimension", "bucket_key"),
    )
    op.create_index("ix_auth_abuse_buckets_expires_at", "auth_abuse_buckets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_abuse_buckets_expires_at", table_name="auth_abuse_buckets")
    op.drop_table("auth_abuse_buckets")
