"""production channel integration

Revision ID: 20260327_010
Revises: 20260326_009
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260327_010"
down_revision = "20260326_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("transport_address_key", sa.String(length=255), nullable=True))
    op.add_column("sessions", sa.Column("transport_address_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_index(
        "ix_sessions_transport_address",
        "sessions",
        ["channel_kind", "channel_account_id", "transport_address_key"],
    )

    op.add_column("outbound_deliveries", sa.Column("delivery_payload_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("outbound_deliveries", sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"))

    op.add_column("outbound_delivery_attempts", sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("outbound_delivery_attempts", sa.Column("retryable", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("outbound_delivery_attempts", "retryable")
    op.drop_column("outbound_delivery_attempts", "provider_metadata_json")
    op.drop_column("outbound_deliveries", "provider_metadata_json")
    op.drop_column("outbound_deliveries", "delivery_payload_json")
    op.drop_index("ix_sessions_transport_address", table_name="sessions")
    op.drop_column("sessions", "transport_address_json")
    op.drop_column("sessions", "transport_address_key")
