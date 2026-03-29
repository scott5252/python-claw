"""sub-agent delegation and child session orchestration

Revision ID: 20260329_015
Revises: 20260328_014
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260329_015"
down_revision = "20260328_014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delegations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("parent_session_id", sa.String(length=36), nullable=False),
        sa.Column("parent_message_id", sa.Integer(), nullable=False),
        sa.Column("parent_run_id", sa.String(length=36), nullable=False),
        sa.Column("parent_tool_call_correlation_id", sa.String(length=64), nullable=False),
        sa.Column("parent_agent_id", sa.String(length=255), nullable=False),
        sa.Column("child_session_id", sa.String(length=36), nullable=False),
        sa.Column("child_message_id", sa.Integer(), nullable=False),
        sa.Column("child_run_id", sa.String(length=36), nullable=False),
        sa.Column("child_agent_id", sa.String(length=255), nullable=False),
        sa.Column("parent_result_message_id", sa.Integer(), nullable=True),
        sa.Column("parent_result_run_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("delegation_kind", sa.String(length=64), nullable=False),
        sa.Column("task_text", sa.Text(), nullable=False),
        sa.Column("context_payload_json", sa.Text(), nullable=False),
        sa.Column("result_payload_json", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["child_agent_id"], ["agent_profiles.agent_id"]),
        sa.ForeignKeyConstraint(["child_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["child_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["child_session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["parent_agent_id"], ["agent_profiles.agent_id"]),
        sa.ForeignKeyConstraint(["parent_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["parent_result_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["parent_result_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["parent_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["parent_session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_run_id",
            "parent_tool_call_correlation_id",
            name="uq_delegations_parent_run_correlation",
        ),
    )
    op.create_index("ix_delegations_parent_session_created", "delegations", ["parent_session_id", "created_at"])
    op.create_index("ix_delegations_parent_run_created", "delegations", ["parent_run_id", "created_at"])
    op.create_index("ix_delegations_child_session_created", "delegations", ["child_session_id", "created_at"])
    op.create_index("ix_delegations_child_run", "delegations", ["child_run_id"])
    op.create_index("ix_delegations_status_updated", "delegations", ["status", "updated_at"])
    op.create_index("ix_delegations_parent_result_run", "delegations", ["parent_result_run_id"])

    op.create_table(
        "delegation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delegation_id", sa.String(length=36), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_ref", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["delegation_id"], ["delegations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delegation_events_delegation_id_id", "delegation_events", ["delegation_id", "id"])
    op.create_index("ix_delegation_events_created_at", "delegation_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_delegation_events_created_at", table_name="delegation_events")
    op.drop_index("ix_delegation_events_delegation_id_id", table_name="delegation_events")
    op.drop_table("delegation_events")
    op.drop_index("ix_delegations_parent_result_run", table_name="delegations")
    op.drop_index("ix_delegations_status_updated", table_name="delegations")
    op.drop_index("ix_delegations_child_run", table_name="delegations")
    op.drop_index("ix_delegations_child_session_created", table_name="delegations")
    op.drop_index("ix_delegations_parent_run_created", table_name="delegations")
    op.drop_index("ix_delegations_parent_session_created", table_name="delegations")
    op.drop_table("delegations")
