"""add channels media persistence

Revision ID: 20260324_007
Revises: 20260324_006
Create Date: 2026-03-24 18:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_007"
down_revision = "20260324_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_message_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("external_attachment_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inbound_message_attachments_message_ordinal",
        "inbound_message_attachments",
        ["message_id", "ordinal"],
    )
    op.create_index(
        "ix_inbound_message_attachments_session_created",
        "inbound_message_attachments",
        ["session_id", "created_at"],
    )

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_attachment_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("external_attachment_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("media_kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("normalization_status", sa.String(length=32), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["inbound_message_attachment_id"], ["inbound_message_attachments.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_attachments_message_ordinal",
        "message_attachments",
        ["message_id", "ordinal"],
    )
    op.create_index(
        "ix_message_attachments_session_created",
        "message_attachments",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_message_attachments_inbound_created",
        "message_attachments",
        ["inbound_message_attachment_id", "created_at"],
    )

    op.create_table(
        "outbound_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=False),
        sa.Column("outbound_intent_id", sa.Integer(), nullable=False),
        sa.Column("channel_kind", sa.String(length=64), nullable=False),
        sa.Column("channel_account_id", sa.String(length=255), nullable=False),
        sa.Column("delivery_kind", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("reply_to_external_id", sa.String(length=255), nullable=True),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"]),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"]),
        sa.ForeignKeyConstraint(["outbound_intent_id"], ["session_artifacts.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbound_intent_id", "chunk_index", name="uq_outbound_deliveries_intent_chunk"),
    )
    op.create_index(
        "ix_outbound_deliveries_intent_chunk",
        "outbound_deliveries",
        ["outbound_intent_id", "chunk_index"],
    )
    op.create_index(
        "ix_outbound_deliveries_session_created",
        "outbound_deliveries",
        ["session_id", "created_at"],
    )

    op.create_table(
        "outbound_delivery_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbound_delivery_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbound_delivery_id"], ["outbound_deliveries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbound_delivery_id", "attempt_number", name="uq_outbound_delivery_attempts_number"),
    )


def downgrade() -> None:
    op.drop_table("outbound_delivery_attempts")
    op.drop_index("ix_outbound_deliveries_session_created", table_name="outbound_deliveries")
    op.drop_index("ix_outbound_deliveries_intent_chunk", table_name="outbound_deliveries")
    op.drop_table("outbound_deliveries")
    op.drop_index("ix_message_attachments_inbound_created", table_name="message_attachments")
    op.drop_index("ix_message_attachments_session_created", table_name="message_attachments")
    op.drop_index("ix_message_attachments_message_ordinal", table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_index("ix_inbound_message_attachments_session_created", table_name="inbound_message_attachments")
    op.drop_index("ix_inbound_message_attachments_message_ordinal", table_name="inbound_message_attachments")
    op.drop_table("inbound_message_attachments")
