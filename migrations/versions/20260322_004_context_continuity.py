"""add context continuity tables

Revision ID: 20260322_004
Revises: 20260322_003
Create Date: 2026-03-22 20:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_004"
down_revision = "20260322_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summary_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("base_message_id", sa.Integer(), nullable=False),
        sa.Column("through_message_id", sa.Integer(), nullable=False),
        sa.Column("source_watermark_message_id", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("summary_metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["base_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["through_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["source_watermark_message_id"], ["messages.id"]),
        sa.UniqueConstraint("session_id", "snapshot_version", name="uq_summary_snapshots_session_version"),
    )
    op.create_index(
        "ix_summary_snapshots_session_through_message_id",
        "summary_snapshots",
        ["session_id", "through_message_id"],
    )

    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("job_kind", sa.String(length=64), nullable=False),
        sa.Column("job_dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.UniqueConstraint("job_dedupe_key", name="uq_outbox_jobs_job_dedupe_key"),
    )
    op.create_index(
        "ix_outbox_jobs_session_status_available_at",
        "outbox_jobs",
        ["session_id", "status", "available_at"],
    )

    op.create_table(
        "context_manifests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
    )
    op.create_index(
        "ix_context_manifests_session_created_at",
        "context_manifests",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_context_manifests_message_id",
        "context_manifests",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_manifests_message_id", table_name="context_manifests")
    op.drop_index("ix_context_manifests_session_created_at", table_name="context_manifests")
    op.drop_table("context_manifests")
    op.drop_index("ix_outbox_jobs_session_status_available_at", table_name="outbox_jobs")
    op.drop_table("outbox_jobs")
    op.drop_index("ix_summary_snapshots_session_through_message_id", table_name="summary_snapshots")
    op.drop_table("summary_snapshots")
