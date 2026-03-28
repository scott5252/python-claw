"""streaming real-time delivery

Revision ID: 20260328_013
Revises: 20260327_010
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260328_013"
down_revision = "20260327_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbound_deliveries", sa.Column("completion_status", sa.String(length=32), nullable=True))

    op.add_column("outbound_delivery_attempts", sa.Column("stream_status", sa.String(length=32), nullable=True))
    op.add_column("outbound_delivery_attempts", sa.Column("provider_stream_id", sa.String(length=255), nullable=True))
    op.add_column(
        "outbound_delivery_attempts",
        sa.Column("last_sequence_number", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("outbound_delivery_attempts", sa.Column("completion_reason", sa.String(length=128), nullable=True))

    op.create_table(
        "outbound_delivery_stream_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("outbound_delivery_id", sa.Integer(), nullable=False),
        sa.Column("outbound_delivery_attempt_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbound_delivery_attempt_id"], ["outbound_delivery_attempts.id"]),
        sa.ForeignKeyConstraint(["outbound_delivery_id"], ["outbound_deliveries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outbound_delivery_attempt_id",
            "sequence_number",
            name="uq_outbound_delivery_stream_events_attempt_sequence",
        ),
    )
    op.create_index(
        "ix_outbound_delivery_stream_events_attempt_sequence",
        "outbound_delivery_stream_events",
        ["outbound_delivery_attempt_id", "sequence_number"],
    )
    op.create_index(
        "ix_outbound_delivery_stream_events_created",
        "outbound_delivery_stream_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_delivery_stream_events_created", table_name="outbound_delivery_stream_events")
    op.drop_index("ix_outbound_delivery_stream_events_attempt_sequence", table_name="outbound_delivery_stream_events")
    op.drop_table("outbound_delivery_stream_events")

    op.drop_column("outbound_delivery_attempts", "completion_reason")
    op.drop_column("outbound_delivery_attempts", "last_sequence_number")
    op.drop_column("outbound_delivery_attempts", "provider_stream_id")
    op.drop_column("outbound_delivery_attempts", "stream_status")

    op.drop_column("outbound_deliveries", "completion_status")
