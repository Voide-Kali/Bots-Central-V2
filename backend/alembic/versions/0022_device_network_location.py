"""Localizacao de rede opt-in do computador (ADR-036): ultimo IP publico e IPs locais.

Guarda so o estado atual no proprio device (nao serie temporal). Preenchido pelo claim
`net` do heartbeat quando o sensor network_location esta ligado no agente.

Revision ID: 0022_device_network_location
Revises: 0021_drop_email_seen
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0022_device_network_location"
down_revision = "0021_drop_email_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("last_public_ip", sa.String(length=45), nullable=True))
    op.add_column(
        "devices",
        sa.Column("last_local_ips", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "devices",
        sa.Column("network_reported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devices", "network_reported_at")
    op.drop_column("devices", "last_local_ips")
    op.drop_column("devices", "last_public_ip")
