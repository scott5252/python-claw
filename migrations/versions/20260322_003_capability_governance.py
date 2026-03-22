"""add capability governance tables

Revision ID: 20260322_003
Revises: 20260322_002
Create Date: 2026-03-22 00:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_003"
down_revision = "20260322_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column("resource_kind", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("current_state", sa.String(length=32), nullable=False),
        sa.Column("latest_version_id", sa.String(length=36), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pending_approval_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("denied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
    )
    op.create_index("ix_resource_proposals_session_state", "resource_proposals", ["session_id", "current_state"])
    op.create_index("ix_resource_proposals_latest_version_id", "resource_proposals", ["latest_version_id"])

    op.create_table(
        "resource_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("resource_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["resource_proposals.id"]),
        sa.UniqueConstraint("proposal_id", "version_number", name="uq_resource_versions_proposal_version"),
    )
    op.create_index("ix_resource_versions_content_hash", "resource_versions", ["content_hash"])

    op.create_table(
        "resource_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("resource_version_id", sa.String(length=36), nullable=False),
        sa.Column("approval_packet_hash", sa.String(length=64), nullable=False),
        sa.Column("typed_action_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_params_json", sa.Text(), nullable=False),
        sa.Column("canonical_params_hash", sa.String(length=64), nullable=False),
        sa.Column("scope_kind", sa.String(length=64), nullable=False),
        sa.Column("approver_id", sa.String(length=255), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["proposal_id"], ["resource_proposals.id"]),
        sa.ForeignKeyConstraint(["resource_version_id"], ["resource_versions.id"]),
        sa.UniqueConstraint(
            "proposal_id",
            "resource_version_id",
            "typed_action_id",
            "canonical_params_hash",
            name="uq_resource_approvals_exact_match",
        ),
    )
    op.create_index(
        "ix_resource_approvals_lookup",
        "resource_approvals",
        ["resource_version_id", "typed_action_id", "canonical_params_hash"],
    )

    op.create_table(
        "active_resources",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("resource_version_id", sa.String(length=36), nullable=False),
        sa.Column("typed_action_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_params_hash", sa.String(length=64), nullable=False),
        sa.Column("activation_state", sa.String(length=32), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["proposal_id"], ["resource_proposals.id"]),
        sa.ForeignKeyConstraint(["resource_version_id"], ["resource_versions.id"]),
        sa.UniqueConstraint(
            "proposal_id",
            "resource_version_id",
            "typed_action_id",
            "canonical_params_hash",
            name="uq_active_resources_activation_identity",
        ),
    )
    op.create_index("ix_active_resources_lookup", "active_resources", ["resource_version_id", "activation_state"])

    op.create_table(
        "governance_transcript_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("resource_version_id", sa.String(length=36), nullable=True),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("active_resource_id", sa.String(length=36), nullable=True),
        sa.Column("event_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["resource_proposals.id"]),
        sa.ForeignKeyConstraint(["resource_version_id"], ["resource_versions.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["resource_approvals.id"]),
        sa.ForeignKeyConstraint(["active_resource_id"], ["active_resources.id"]),
    )
    op.create_index(
        "ix_governance_transcript_events_session_id_id",
        "governance_transcript_events",
        ["session_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_governance_transcript_events_session_id_id", table_name="governance_transcript_events")
    op.drop_table("governance_transcript_events")
    op.drop_index("ix_active_resources_lookup", table_name="active_resources")
    op.drop_table("active_resources")
    op.drop_index("ix_resource_approvals_lookup", table_name="resource_approvals")
    op.drop_table("resource_approvals")
    op.drop_index("ix_resource_versions_content_hash", table_name="resource_versions")
    op.drop_table("resource_versions")
    op.drop_index("ix_resource_proposals_latest_version_id", table_name="resource_proposals")
    op.drop_index("ix_resource_proposals_session_state", table_name="resource_proposals")
    op.drop_table("resource_proposals")
