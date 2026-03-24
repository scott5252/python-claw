from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScopeKind(str, Enum):
    DIRECT = "direct"
    GROUP = "group"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class DedupeStatus(str, Enum):
    CLAIMED = "claimed"
    COMPLETED = "completed"


class ExecutionRunStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class NodeExecutionStatus(str, Enum):
    RECEIVED = "received"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_sessions_session_key"),
        Index(
            "ix_sessions_direct_lookup",
            "channel_kind",
            "channel_account_id",
            "peer_id",
            "scope_name",
        ),
        Index(
            "ix_sessions_group_lookup",
            "channel_kind",
            "channel_account_id",
            "group_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_key: Mapped[str] = mapped_column(String(512), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    peer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    messages: Mapped[list["MessageRecord"]] = relationship(back_populates="session")


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    session: Mapped["SessionRecord"] = relationship(back_populates="messages")


class InboundMessageAttachmentRecord(Base):
    __tablename__ = "inbound_message_attachments"
    __table_args__ = (
        Index("ix_inbound_message_attachments_message_ordinal", "message_id", "ordinal"),
        Index("ix_inbound_message_attachments_session_created", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    external_attachment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MessageAttachmentRecord(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        Index("ix_message_attachments_message_ordinal", "message_id", "ordinal"),
        Index("ix_message_attachments_session_created", "session_id", "created_at"),
        Index("ix_message_attachments_inbound_created", "inbound_message_attachment_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inbound_message_attachment_id: Mapped[int] = mapped_column(
        ForeignKey("inbound_message_attachments.id"),
        nullable=False,
    )
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    external_attachment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalization_status: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SessionArtifactRecord(Base):
    __tablename__ = "session_artifacts"
    __table_args__ = (
        Index("ix_session_artifacts_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ToolAuditEventRecord(Base):
    __tablename__ = "tool_audit_events"
    __table_args__ = (
        Index("ix_tool_audit_events_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InboundDedupeRecord(Base):
    __tablename__ = "inbound_dedupe"
    __table_args__ = (
        UniqueConstraint(
            "channel_kind",
            "channel_account_id",
            "external_message_id",
            name="uq_inbound_dedupe_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionRunRecord(Base):
    __tablename__ = "execution_runs"
    __table_args__ = (
        UniqueConstraint("trigger_kind", "trigger_ref", name="uq_execution_runs_trigger_identity"),
        Index("ix_execution_runs_status_available_created_id", "status", "available_at", "created_at", "id"),
        Index("ix_execution_runs_session_status_created", "session_id", "status", "created_at"),
        Index("ix_execution_runs_lane_status_available", "lane_key", "status", "available_at"),
        Index("ix_execution_runs_worker_status", "worker_id", "status"),
        Index("ix_execution_runs_status_updated", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    lane_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    degraded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class SessionRunLeaseRecord(Base):
    __tablename__ = "session_run_leases"
    __table_args__ = (
        UniqueConstraint("lane_key", name="uq_session_run_leases_lane_key"),
        UniqueConstraint("execution_run_id", name="uq_session_run_leases_execution_run_id"),
        Index("ix_session_run_leases_worker_expiry", "worker_id", "lease_expires_at"),
    )

    lane_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    execution_run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class GlobalRunLeaseRecord(Base):
    __tablename__ = "global_run_leases"
    __table_args__ = (
        UniqueConstraint("execution_run_id", name="uq_global_run_leases_execution_run_id"),
        Index("ix_global_run_leases_worker_expiry", "worker_id", "lease_expires_at"),
    )

    slot_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    execution_run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ScheduledJobRecord(Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("job_key", name="uq_scheduled_jobs_job_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    job_key: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    channel_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    peer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cron_expr: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ScheduledJobFireRecord(Base):
    __tablename__ = "scheduled_job_fires"
    __table_args__ = (
        UniqueConstraint("fire_key", name="uq_scheduled_job_fires_fire_key"),
        Index("ix_scheduled_job_fires_job_scheduled_for", "scheduled_job_id", "scheduled_for"),
        Index("ix_scheduled_job_fires_status_scheduled_for", "status", "scheduled_for"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scheduled_job_id: Mapped[str] = mapped_column(ForeignKey("scheduled_jobs.id"), nullable=False)
    fire_key: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class GovernanceTranscriptEventRecord(Base):
    __tablename__ = "governance_transcript_events"
    __table_args__ = (
        Index("ix_governance_transcript_events_session_id_id", "session_id", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("resource_proposals.id"), nullable=True)
    resource_version_id: Mapped[str | None] = mapped_column(ForeignKey("resource_versions.id"), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("resource_approvals.id"), nullable=True)
    active_resource_id: Mapped[str | None] = mapped_column(ForeignKey("active_resources.id"), nullable=True)
    event_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResourceProposalRecord(Base):
    __tablename__ = "resource_proposals"
    __table_args__ = (
        Index("ix_resource_proposals_session_state", "session_id", "current_state"),
        Index("ix_resource_proposals_latest_version_id", "latest_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    current_state: Mapped[str] = mapped_column(String(32), nullable=False)
    latest_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    pending_approval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    denied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResourceVersionRecord(Base):
    __tablename__ = "resource_versions"
    __table_args__ = (
        UniqueConstraint("proposal_id", "version_number", name="uq_resource_versions_proposal_version"),
        Index("ix_resource_versions_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("resource_proposals.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResourceApprovalRecord(Base):
    __tablename__ = "resource_approvals"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id",
            "resource_version_id",
            "typed_action_id",
            "canonical_params_hash",
            name="uq_resource_approvals_exact_match",
        ),
        Index(
            "ix_resource_approvals_lookup",
            "resource_version_id",
            "typed_action_id",
            "canonical_params_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("resource_proposals.id"), nullable=False)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_versions.id"), nullable=False)
    approval_packet_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    typed_action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_params_json: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_id: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ActiveResourceRecord(Base):
    __tablename__ = "active_resources"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id",
            "resource_version_id",
            "typed_action_id",
            "canonical_params_hash",
            name="uq_active_resources_activation_identity",
        ),
        Index("ix_active_resources_lookup", "resource_version_id", "activation_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("resource_proposals.id"), nullable=False)
    resource_version_id: Mapped[str] = mapped_column(ForeignKey("resource_versions.id"), nullable=False)
    typed_action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SummarySnapshotRecord(Base):
    __tablename__ = "summary_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", "snapshot_version", name="uq_summary_snapshots_session_version"),
        Index("ix_summary_snapshots_session_through_message_id", "session_id", "through_message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    through_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    source_watermark_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OutboxJobRecord(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        UniqueConstraint("job_dedupe_key", name="uq_outbox_jobs_job_dedupe_key"),
        Index("ix_outbox_jobs_session_status_available_at", "session_id", "status", "available_at"),
        Index("ix_outbox_jobs_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    job_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    job_dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ContextManifestRecord(Base):
    __tablename__ = "context_manifests"
    __table_args__ = (
        Index("ix_context_manifests_session_created_at", "session_id", "created_at"),
        Index("ix_context_manifests_message_id", "message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    degraded: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OutboundDeliveryRecord(Base):
    __tablename__ = "outbound_deliveries"
    __table_args__ = (
        UniqueConstraint("outbound_intent_id", "chunk_index", name="uq_outbound_deliveries_intent_chunk"),
        Index("ix_outbound_deliveries_intent_chunk", "outbound_intent_id", "chunk_index"),
        Index("ix_outbound_deliveries_session_created", "session_id", "created_at"),
        Index("ix_outbound_deliveries_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    execution_run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    outbound_intent_id: Mapped[int] = mapped_column(ForeignKey("session_artifacts.id"), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reply_to_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey("message_attachments.id"), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OutboundDeliveryAttemptRecord(Base):
    __tablename__ = "outbound_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("outbound_delivery_id", "attempt_number", name="uq_outbound_delivery_attempts_number"),
        Index("ix_outbound_delivery_attempts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbound_delivery_id: Mapped[int] = mapped_column(ForeignKey("outbound_deliveries.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class NodeExecutionAuditRecord(Base):
    __tablename__ = "node_execution_audits"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_node_execution_audits_request_id"),
        Index("ix_node_execution_audits_execution_run_created", "execution_run_id", "created_at"),
        Index("ix_node_execution_audits_session_created", "session_id", "created_at"),
        Index("ix_node_execution_audits_agent_created", "agent_id", "created_at"),
        Index("ix_node_execution_audits_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sandbox_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    sandbox_key: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_root: Mapped[str] = mapped_column(String(1024), nullable=False)
    workspace_mount_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    command_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    typed_action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("resource_approvals.id"), nullable=True)
    resource_version_id: Mapped[str | None] = mapped_column(ForeignKey("resource_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    deny_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stdout_truncated: Mapped[bool] = mapped_column(nullable=False, default=False)
    stderr_truncated: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AgentSandboxProfileRecord(Base):
    __tablename__ = "agent_sandbox_profiles"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_sandbox_profiles_agent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    default_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    shared_profile_key: Mapped[str] = mapped_column(String(255), nullable=False)
    allow_off_mode: Mapped[bool] = mapped_column(nullable=False, default=False)
    max_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
