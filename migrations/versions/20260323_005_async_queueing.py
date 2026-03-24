"""add async queueing tables

Revision ID: 20260323_005
Revises: 20260322_004
Create Date: 2026-03-23 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_005"
down_revision = "20260322_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("trigger_kind", sa.String(length=32), nullable=False),
        sa.Column("trigger_ref", sa.String(length=255), nullable=False),
        sa.Column("lane_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trigger_kind", "trigger_ref", name="uq_execution_runs_trigger_identity"),
    )
    op.create_index(
        "ix_execution_runs_status_available_created_id",
        "execution_runs",
        ["status", "available_at", "created_at", "id"],
    )
    op.create_index(
        "ix_execution_runs_session_status_created",
        "execution_runs",
        ["session_id", "status", "created_at"],
    )
    op.create_index(
        "ix_execution_runs_lane_status_available",
        "execution_runs",
        ["lane_key", "status", "available_at"],
    )
    op.create_index(
        "ix_execution_runs_worker_status",
        "execution_runs",
        ["worker_id", "status"],
    )

    op.create_table(
        "session_run_leases",
        sa.Column("lane_key", sa.String(length=255), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
        sa.PrimaryKeyConstraint("lane_key"),
        sa.UniqueConstraint("execution_run_id", name="uq_session_run_leases_execution_run_id"),
    )
    op.create_index(
        "ix_session_run_leases_worker_expiry",
        "session_run_leases",
        ["worker_id", "lease_expires_at"],
    )

    op.create_table(
        "global_run_leases",
        sa.Column("slot_key", sa.String(length=32), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
        sa.PrimaryKeyConstraint("slot_key"),
        sa.UniqueConstraint("execution_run_id", name="uq_global_run_leases_execution_run_id"),
    )
    op.create_index(
        "ix_global_run_leases_worker_expiry",
        "global_run_leases",
        ["worker_id", "lease_expires_at"],
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_key", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("channel_kind", sa.String(length=64), nullable=True),
        sa.Column("channel_account_id", sa.String(length=255), nullable=True),
        sa.Column("peer_id", sa.String(length=255), nullable=True),
        sa.Column("group_id", sa.String(length=255), nullable=True),
        sa.Column("cron_expr", sa.String(length=255), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_key", name="uq_scheduled_jobs_job_key"),
    )

    op.create_table(
        "scheduled_job_fires",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_job_id", sa.String(length=36), nullable=False),
        sa.Column("fire_key", sa.String(length=255), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["scheduled_job_id"], ["scheduled_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fire_key", name="uq_scheduled_job_fires_fire_key"),
    )
    op.create_index(
        "ix_scheduled_job_fires_job_scheduled_for",
        "scheduled_job_fires",
        ["scheduled_job_id", "scheduled_for"],
    )
    op.create_index(
        "ix_scheduled_job_fires_status_scheduled_for",
        "scheduled_job_fires",
        ["status", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_job_fires_status_scheduled_for", table_name="scheduled_job_fires")
    op.drop_index("ix_scheduled_job_fires_job_scheduled_for", table_name="scheduled_job_fires")
    op.drop_table("scheduled_job_fires")
    op.drop_table("scheduled_jobs")
    op.drop_index("ix_global_run_leases_worker_expiry", table_name="global_run_leases")
    op.drop_table("global_run_leases")
    op.drop_index("ix_session_run_leases_worker_expiry", table_name="session_run_leases")
    op.drop_table("session_run_leases")
    op.drop_index("ix_execution_runs_worker_status", table_name="execution_runs")
    op.drop_index("ix_execution_runs_lane_status_available", table_name="execution_runs")
    op.drop_index("ix_execution_runs_session_status_created", table_name="execution_runs")
    op.drop_index("ix_execution_runs_status_available_created_id", table_name="execution_runs")
    op.drop_table("execution_runs")
