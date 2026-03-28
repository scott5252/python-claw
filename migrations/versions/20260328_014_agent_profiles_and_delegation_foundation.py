"""agent profiles and delegation foundation

Revision ID: 20260328_014
Revises: 20260328_013
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260328_014"
down_revision = "20260328_013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_key", sa.String(length=255), nullable=False),
        sa.Column("runtime_mode", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("temperature", sa.String(length=64), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("tool_call_mode", sa.String(length=32), nullable=False),
        sa.Column("streaming_enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_key", name="uq_model_profiles_profile_key"),
    )
    op.create_index("ix_model_profiles_enabled_runtime_mode", "model_profiles", ["enabled", "runtime_mode"])

    op.create_table(
        "agent_profiles",
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role_kind", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_model_profile_id", sa.Integer(), nullable=False),
        sa.Column("policy_profile_key", sa.String(length=255), nullable=False),
        sa.Column("tool_profile_key", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["default_model_profile_id"], ["model_profiles.id"]),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_profiles_agent_id"),
    )
    op.create_index("ix_agent_profiles_enabled_role_kind", "agent_profiles", ["enabled", "role_kind"])
    op.create_index("ix_agent_profiles_default_model_profile_id", "agent_profiles", ["default_model_profile_id"])

    op.add_column("sessions", sa.Column("owner_agent_id", sa.String(length=255), nullable=True))
    op.add_column("sessions", sa.Column("session_kind", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("parent_session_id", sa.String(length=36), nullable=True))
    op.create_index("ix_sessions_owner_agent_created", "sessions", ["owner_agent_id", "created_at"])
    op.create_index("ix_sessions_parent_created", "sessions", ["parent_session_id", "created_at"])
    op.create_index("ix_sessions_session_kind_created", "sessions", ["session_kind", "created_at"])

    op.add_column("execution_runs", sa.Column("model_profile_key", sa.String(length=255), nullable=True))
    op.add_column("execution_runs", sa.Column("policy_profile_key", sa.String(length=255), nullable=True))
    op.add_column("execution_runs", sa.Column("tool_profile_key", sa.String(length=255), nullable=True))
    op.create_index("ix_execution_runs_agent_created", "execution_runs", ["agent_id", "created_at"])
    op.create_index("ix_execution_runs_model_profile_created", "execution_runs", ["model_profile_key", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_runs_model_profile_created", table_name="execution_runs")
    op.drop_index("ix_execution_runs_agent_created", table_name="execution_runs")
    op.drop_column("execution_runs", "tool_profile_key")
    op.drop_column("execution_runs", "policy_profile_key")
    op.drop_column("execution_runs", "model_profile_key")

    op.drop_index("ix_sessions_session_kind_created", table_name="sessions")
    op.drop_index("ix_sessions_parent_created", table_name="sessions")
    op.drop_index("ix_sessions_owner_agent_created", table_name="sessions")
    op.drop_column("sessions", "parent_session_id")
    op.drop_column("sessions", "session_kind")
    op.drop_column("sessions", "owner_agent_id")

    op.drop_index("ix_agent_profiles_default_model_profile_id", table_name="agent_profiles")
    op.drop_index("ix_agent_profiles_enabled_role_kind", table_name="agent_profiles")
    op.drop_table("agent_profiles")

    op.drop_index("ix_model_profiles_enabled_runtime_mode", table_name="model_profiles")
    op.drop_table("model_profiles")
