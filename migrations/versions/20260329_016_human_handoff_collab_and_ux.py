"""human handoff collaboration and approval ux

Revision ID: 20260329_016
Revises: 20260329_015
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260329_016"
down_revision = "20260329_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("automation_state", sa.String(length=32), nullable=True))
    op.add_column("sessions", sa.Column("assigned_operator_id", sa.String(length=255), nullable=True))
    op.add_column("sessions", sa.Column("assigned_queue_key", sa.String(length=255), nullable=True))
    op.add_column("sessions", sa.Column("automation_state_reason", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("automation_state_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("assignment_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("collaboration_version", sa.Integer(), nullable=True))
    op.execute("UPDATE sessions SET automation_state = 'assistant_active' WHERE automation_state IS NULL")
    op.execute("UPDATE sessions SET automation_state_changed_at = created_at WHERE automation_state_changed_at IS NULL")
    op.execute("UPDATE sessions SET collaboration_version = 1 WHERE collaboration_version IS NULL")
    op.alter_column("sessions", "automation_state", nullable=False)
    op.alter_column("sessions", "automation_state_changed_at", nullable=False)
    op.alter_column("sessions", "collaboration_version", nullable=False)
    op.create_index("ix_sessions_automation_state_activity", "sessions", ["automation_state", "last_activity_at"])
    op.create_index("ix_sessions_assigned_operator_activity", "sessions", ["assigned_operator_id", "last_activity_at"])
    op.create_index("ix_sessions_assigned_queue_activity", "sessions", ["assigned_queue_key", "last_activity_at"])

    op.add_column("execution_runs", sa.Column("blocked_reason", sa.String(length=128), nullable=True))
    op.add_column("execution_runs", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_execution_runs_status_blocked_created", "execution_runs", ["status", "blocked_at", "created_at"])

    op.create_table(
        "session_operator_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("author_kind", sa.String(length=32), nullable=False),
        sa.Column("author_id", sa.String(length=255), nullable=True),
        sa.Column("note_kind", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_operator_notes_session_id_id", "session_operator_notes", ["session_id", "id"])
    op.create_index("ix_session_operator_notes_author_created", "session_operator_notes", ["author_id", "created_at"])

    op.create_table(
        "session_collaboration_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=True),
        sa.Column("automation_state_before", sa.String(length=32), nullable=True),
        sa.Column("automation_state_after", sa.String(length=32), nullable=True),
        sa.Column("assigned_operator_before", sa.String(length=255), nullable=True),
        sa.Column("assigned_operator_after", sa.String(length=255), nullable=True),
        sa.Column("assigned_queue_before", sa.String(length=255), nullable=True),
        sa.Column("assigned_queue_after", sa.String(length=255), nullable=True),
        sa.Column("related_run_id", sa.String(length=36), nullable=True),
        sa.Column("related_note_id", sa.Integer(), nullable=True),
        sa.Column("related_proposal_id", sa.String(length=36), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["related_note_id"], ["session_operator_notes.id"]),
        sa.ForeignKeyConstraint(["related_proposal_id"], ["resource_proposals.id"]),
        sa.ForeignKeyConstraint(["related_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_collaboration_events_session_id_id", "session_collaboration_events", ["session_id", "id"])
    op.create_index("ix_session_collaboration_events_event_created", "session_collaboration_events", ["event_kind", "created_at"])
    op.create_index("ix_session_collaboration_events_actor_created", "session_collaboration_events", ["actor_kind", "actor_id", "created_at"])

    op.create_table(
        "approval_action_prompts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("channel_kind", sa.String(length=64), nullable=False),
        sa.Column("channel_account_id", sa.String(length=255), nullable=False),
        sa.Column("transport_address_key", sa.String(length=255), nullable=True),
        sa.Column("approve_token_hash", sa.String(length=64), nullable=False),
        sa.Column("deny_token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_via", sa.String(length=64), nullable=True),
        sa.Column("decider_actor_id", sa.String(length=255), nullable=True),
        sa.Column("presentation_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["resource_proposals.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approve_token_hash", name="uq_approval_action_prompts_approve_hash"),
        sa.UniqueConstraint("deny_token_hash", name="uq_approval_action_prompts_deny_hash"),
    )
    op.create_index("ix_approval_action_prompts_proposal_created", "approval_action_prompts", ["proposal_id", "created_at"])
    op.create_index("ix_approval_action_prompts_session_status_created", "approval_action_prompts", ["session_id", "status", "created_at"])
    op.create_index("ix_approval_action_prompts_status_expires", "approval_action_prompts", ["status", "expires_at"])

    op.add_column("governance_transcript_events", sa.Column("approval_prompt_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_governance_transcript_events_approval_prompt_id",
        "governance_transcript_events",
        "approval_action_prompts",
        ["approval_prompt_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_governance_transcript_events_approval_prompt_id", "governance_transcript_events", type_="foreignkey")
    op.drop_column("governance_transcript_events", "approval_prompt_id")

    op.drop_index("ix_approval_action_prompts_status_expires", table_name="approval_action_prompts")
    op.drop_index("ix_approval_action_prompts_session_status_created", table_name="approval_action_prompts")
    op.drop_index("ix_approval_action_prompts_proposal_created", table_name="approval_action_prompts")
    op.drop_table("approval_action_prompts")

    op.drop_index("ix_session_collaboration_events_actor_created", table_name="session_collaboration_events")
    op.drop_index("ix_session_collaboration_events_event_created", table_name="session_collaboration_events")
    op.drop_index("ix_session_collaboration_events_session_id_id", table_name="session_collaboration_events")
    op.drop_table("session_collaboration_events")

    op.drop_index("ix_session_operator_notes_author_created", table_name="session_operator_notes")
    op.drop_index("ix_session_operator_notes_session_id_id", table_name="session_operator_notes")
    op.drop_table("session_operator_notes")

    op.drop_index("ix_execution_runs_status_blocked_created", table_name="execution_runs")
    op.drop_column("execution_runs", "blocked_at")
    op.drop_column("execution_runs", "blocked_reason")

    op.drop_index("ix_sessions_assigned_queue_activity", table_name="sessions")
    op.drop_index("ix_sessions_assigned_operator_activity", table_name="sessions")
    op.drop_index("ix_sessions_automation_state_activity", table_name="sessions")
    op.drop_column("sessions", "collaboration_version")
    op.drop_column("sessions", "assignment_updated_at")
    op.drop_column("sessions", "automation_state_changed_at")
    op.drop_column("sessions", "automation_state_reason")
    op.drop_column("sessions", "assigned_queue_key")
    op.drop_column("sessions", "assigned_operator_id")
    op.drop_column("sessions", "automation_state")
