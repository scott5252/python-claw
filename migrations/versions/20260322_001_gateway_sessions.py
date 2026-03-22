"""create gateway session foundation tables

Revision ID: 20260322_001
Revises:
Create Date: 2026-03-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260322_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("session_key", sa.String(length=512), nullable=False),
        sa.Column("channel_kind", sa.String(length=64), nullable=False),
        sa.Column("channel_account_id", sa.String(length=255), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("peer_id", sa.String(length=255), nullable=True),
        sa.Column("group_id", sa.String(length=255), nullable=True),
        sa.Column("scope_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_key", name="uq_sessions_session_key"),
    )
    op.create_index(
        "ix_sessions_direct_lookup",
        "sessions",
        ["channel_kind", "channel_account_id", "peer_id", "scope_name"],
    )
    op.create_index(
        "ix_sessions_group_lookup",
        "sessions",
        ["channel_kind", "channel_account_id", "group_id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("sender_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
    )
    op.create_index("ix_messages_session_id_id", "messages", ["session_id", "id"])

    op.create_table(
        "inbound_dedupe",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("channel_kind", sa.String(length=64), nullable=False),
        sa.Column("channel_account_id", sa.String(length=255), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.UniqueConstraint(
            "channel_kind",
            "channel_account_id",
            "external_message_id",
            name="uq_inbound_dedupe_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("inbound_dedupe")
    op.drop_index("ix_messages_session_id_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_sessions_group_lookup", table_name="sessions")
    op.drop_index("ix_sessions_direct_lookup", table_name="sessions")
    op.drop_table("sessions")
