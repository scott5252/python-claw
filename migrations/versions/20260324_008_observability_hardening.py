"""observability hardening

Revision ID: 20260324_008_observability_hardening
Revises: 20260324_007_channels_media
Create Date: 2026-03-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_008_observability_hardening"
down_revision = "20260324_007_channels_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("execution_runs", sa.Column("correlation_id", sa.String(length=255), nullable=True))
    op.add_column("execution_runs", sa.Column("degraded_reason", sa.Text(), nullable=True))
    op.add_column("execution_runs", sa.Column("failure_category", sa.String(length=64), nullable=True))
    op.create_index("ix_execution_runs_status_updated", "execution_runs", ["status", "updated_at"], unique=False)

    op.add_column("outbox_jobs", sa.Column("trace_id", sa.String(length=255), nullable=True))
    op.add_column("outbox_jobs", sa.Column("failure_category", sa.String(length=64), nullable=True))
    op.create_index("ix_outbox_jobs_status_updated", "outbox_jobs", ["status", "updated_at"], unique=False)

    op.add_column("outbound_deliveries", sa.Column("trace_id", sa.String(length=255), nullable=True))
    op.add_column("outbound_deliveries", sa.Column("failure_category", sa.String(length=64), nullable=True))
    op.create_index("ix_outbound_deliveries_status_created", "outbound_deliveries", ["status", "created_at"], unique=False)

    op.add_column("outbound_delivery_attempts", sa.Column("trace_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_outbound_delivery_attempts_status_created",
        "outbound_delivery_attempts",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_delivery_attempts_status_created", table_name="outbound_delivery_attempts")
    op.drop_column("outbound_delivery_attempts", "trace_id")

    op.drop_index("ix_outbound_deliveries_status_created", table_name="outbound_deliveries")
    op.drop_column("outbound_deliveries", "failure_category")
    op.drop_column("outbound_deliveries", "trace_id")

    op.drop_index("ix_outbox_jobs_status_updated", table_name="outbox_jobs")
    op.drop_column("outbox_jobs", "failure_category")
    op.drop_column("outbox_jobs", "trace_id")

    op.drop_index("ix_execution_runs_status_updated", table_name="execution_runs")
    op.drop_column("execution_runs", "failure_category")
    op.drop_column("execution_runs", "degraded_reason")
    op.drop_column("execution_runs", "correlation_id")
