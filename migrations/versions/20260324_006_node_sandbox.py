"""add node execution audits and sandbox profiles

Revision ID: 20260324_006
Revises: 20260323_005
Create Date: 2026-03-24 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_006"
down_revision = "20260323_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sandbox_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("default_mode", sa.String(length=16), nullable=False),
        sa.Column("shared_profile_key", sa.String(length=255), nullable=False),
        sa.Column("allow_off_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_sandbox_profiles_agent_id"),
    )
    op.create_table(
        "node_execution_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=True),
        sa.Column("tool_call_id", sa.String(length=64), nullable=True),
        sa.Column("execution_attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("requester_kind", sa.String(length=32), nullable=False),
        sa.Column("sandbox_mode", sa.String(length=16), nullable=False),
        sa.Column("sandbox_key", sa.String(length=255), nullable=False),
        sa.Column("workspace_root", sa.String(length=1024), nullable=False),
        sa.Column("workspace_mount_mode", sa.String(length=16), nullable=False),
        sa.Column("command_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("typed_action_id", sa.String(length=128), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("resource_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("deny_reason", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("stdout_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stderr_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["resource_approvals.id"]),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["resource_version_id"], ["resource_versions.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_node_execution_audits_request_id"),
    )
    op.create_index(
        "ix_node_execution_audits_execution_run_created",
        "node_execution_audits",
        ["execution_run_id", "created_at"],
    )
    op.create_index(
        "ix_node_execution_audits_session_created",
        "node_execution_audits",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_node_execution_audits_agent_created",
        "node_execution_audits",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "ix_node_execution_audits_status_created",
        "node_execution_audits",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_node_execution_audits_status_created", table_name="node_execution_audits")
    op.drop_index("ix_node_execution_audits_agent_created", table_name="node_execution_audits")
    op.drop_index("ix_node_execution_audits_session_created", table_name="node_execution_audits")
    op.drop_index("ix_node_execution_audits_execution_run_created", table_name="node_execution_audits")
    op.drop_table("node_execution_audits")
    op.drop_table("agent_sandbox_profiles")
