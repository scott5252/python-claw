"""add runtime tool artifacts and audit events

Revision ID: 20260322_002
Revises: 20260322_001
Create Date: 2026-03-22 00:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_002"
down_revision = "20260322_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_kind", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("capability_name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
    )
    op.create_index("ix_session_artifacts_session_id_id", "session_artifacts", ["session_id", "id"])

    op.create_table(
        "tool_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("capability_name", sa.String(length=128), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
    )
    op.create_index("ix_tool_audit_events_session_id_id", "tool_audit_events", ["session_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_tool_audit_events_session_id_id", table_name="tool_audit_events")
    op.drop_table("tool_audit_events")
    op.drop_index("ix_session_artifacts_session_id_id", table_name="session_artifacts")
    op.drop_table("session_artifacts")
