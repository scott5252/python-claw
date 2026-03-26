"""retrieval memory attachment understanding

Revision ID: 20260326_009
Revises: 20260324_008
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_009"
down_revision = "20260324_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_memories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("memory_kind", sa.String(length=64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_summary_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("source_base_message_id", sa.Integer(), nullable=True),
        sa.Column("source_through_message_id", sa.Integer(), nullable=True),
        sa.Column("derivation_strategy_id", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["source_base_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["source_summary_snapshot_id"], ["summary_snapshots.id"]),
        sa.ForeignKeyConstraint(["source_through_message_id"], ["messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_memories_session_status_created", "session_memories", ["session_id", "status", "created_at"])
    op.create_index("ix_session_memories_source_message_status", "session_memories", ["source_message_id", "status"])
    op.create_index("ix_session_memories_source_summary_status", "session_memories", ["source_summary_snapshot_id", "status"])

    op.create_table(
        "attachment_extractions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.Column("extractor_kind", sa.String(length=64), nullable=False),
        sa.Column("derivation_strategy_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attachment_id", "extractor_kind", "derivation_strategy_id", name="uq_attachment_extractions_identity"),
    )
    op.create_index("ix_attachment_extractions_session_status_created", "attachment_extractions", ["session_id", "status", "created_at"])

    op.create_table(
        "retrieval_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_summary_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("source_memory_id", sa.Integer(), nullable=True),
        sa.Column("source_attachment_extraction_id", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ranking_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("derivation_strategy_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["source_attachment_extraction_id"], ["attachment_extractions.id"]),
        sa.ForeignKeyConstraint(["source_memory_id"], ["session_memories.id"]),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["source_summary_snapshot_id"], ["summary_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "source_kind",
            "source_id",
            "chunk_index",
            "content_hash",
            "derivation_strategy_id",
            name="uq_retrieval_records_chunk_identity",
        ),
    )
    op.create_index("ix_retrieval_records_session_source_created", "retrieval_records", ["session_id", "source_kind", "created_at"])

    op.add_column("outbox_jobs", sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("outbox_jobs", "payload_json")
    op.drop_index("ix_retrieval_records_session_source_created", table_name="retrieval_records")
    op.drop_table("retrieval_records")
    op.drop_index("ix_attachment_extractions_session_status_created", table_name="attachment_extractions")
    op.drop_table("attachment_extractions")
    op.drop_index("ix_session_memories_source_summary_status", table_name="session_memories")
    op.drop_index("ix_session_memories_source_message_status", table_name="session_memories")
    op.drop_index("ix_session_memories_session_status_created", table_name="session_memories")
    op.drop_table("session_memories")
