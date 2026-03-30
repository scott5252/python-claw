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
    SYSTEM = "system"


class DedupeStatus(str, Enum):
    CLAIMED = "claimed"
    COMPLETED = "completed"


class ExecutionRunStatus(str, Enum):
    QUEUED = "queued"
    BLOCKED = "blocked"
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


class SessionKind(str, Enum):
    PRIMARY = "primary"
    CHILD = "child"
    SYSTEM = "system"


class SessionAutomationState(str, Enum):
    ASSISTANT_ACTIVE = "assistant_active"
    HUMAN_TAKEOVER = "human_takeover"
    PAUSED = "paused"


class ApprovalActionPromptStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class ModelRuntimeMode(str, Enum):
    RULE_BASED = "rule_based"
    PROVIDER = "provider"


class DelegationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RateLimitCounterRecord(Base):
    __tablename__ = "rate_limit_counters"
    __table_args__ = (
        UniqueConstraint(
            "scope_kind",
            "scope_key",
            "window_seconds",
            "window_start",
            name="uq_rate_limit_counters_scope_window",
        ),
        Index("ix_rate_limit_counters_scope_last_seen", "scope_kind", "last_seen_at"),
        Index("ix_rate_limit_counters_window_start", "window_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ModelProfileRecord(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("profile_key", name="uq_model_profiles_profile_key"),
        Index("ix_model_profiles_enabled_runtime_mode", "enabled", "runtime_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_key: Mapped[str] = mapped_column(String(255), nullable=False)
    runtime_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temperature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_call_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    streaming_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AgentProfileRecord(Base):
    __tablename__ = "agent_profiles"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_profiles_agent_id"),
        Index("ix_agent_profiles_enabled_role_kind", "enabled", "role_kind"),
        Index("ix_agent_profiles_default_model_profile_id", "default_model_profile_id"),
    )

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="assistant")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model_profile_id: Mapped[int] = mapped_column(ForeignKey("model_profiles.id"), nullable=False)
    policy_profile_key: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_profile_key: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    default_model_profile: Mapped["ModelProfileRecord"] = relationship()


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
        Index("ix_sessions_transport_address", "channel_kind", "channel_account_id", "transport_address_key"),
        Index("ix_sessions_owner_agent_created", "owner_agent_id", "created_at"),
        Index("ix_sessions_parent_created", "parent_session_id", "created_at"),
        Index("ix_sessions_session_kind_created", "session_kind", "created_at"),
        Index("ix_sessions_automation_state_activity", "automation_state", "last_activity_at"),
        Index("ix_sessions_assigned_operator_activity", "assigned_operator_id", "last_activity_at"),
        Index("ix_sessions_assigned_queue_activity", "assigned_queue_key", "last_activity_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_key: Mapped[str] = mapped_column(String(512), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    peer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agent_profiles.agent_id"),
        nullable=False,
        default="default-agent",
    )
    session_kind: Mapped[str] = mapped_column(String(16), nullable=False, default=SessionKind.PRIMARY.value)
    parent_session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    transport_address_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transport_address_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    automation_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SessionAutomationState.ASSISTANT_ACTIVE.value,
    )
    assigned_operator_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_queue_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    automation_state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    automation_state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    assignment_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collaboration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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


class DelegationRecord(Base):
    __tablename__ = "delegations"
    __table_args__ = (
        UniqueConstraint(
            "parent_run_id",
            "parent_tool_call_correlation_id",
            name="uq_delegations_parent_run_correlation",
        ),
        Index("ix_delegations_parent_session_created", "parent_session_id", "created_at"),
        Index("ix_delegations_parent_run_created", "parent_run_id", "created_at"),
        Index("ix_delegations_child_session_created", "child_session_id", "created_at"),
        Index("ix_delegations_child_run", "child_run_id"),
        Index("ix_delegations_status_updated", "status", "updated_at"),
        Index("ix_delegations_parent_result_run", "parent_result_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    parent_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    parent_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    parent_run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    parent_tool_call_correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_agent_id: Mapped[str] = mapped_column(ForeignKey("agent_profiles.agent_id"), nullable=False)
    child_session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    child_message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    child_run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), nullable=False)
    child_agent_id: Mapped[str] = mapped_column(ForeignKey("agent_profiles.agent_id"), nullable=False)
    parent_result_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    parent_result_run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DelegationStatus.QUEUED.value)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    delegation_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class DelegationEventRecord(Base):
    __tablename__ = "delegation_events"
    __table_args__ = (
        Index("ix_delegation_events_delegation_id_id", "delegation_id", "id"),
        Index("ix_delegation_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delegation_id: Mapped[str] = mapped_column(ForeignKey("delegations.id"), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


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
        Index("ix_execution_runs_agent_created", "agent_id", "created_at"),
        Index("ix_execution_runs_model_profile_created", "model_profile_key", "created_at"),
        Index("ix_execution_runs_status_blocked_created", "status", "blocked_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_profile_key: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    policy_profile_key: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    tool_profile_key: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
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
    blocked_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class SessionOperatorNoteRecord(Base):
    __tablename__ = "session_operator_notes"
    __table_args__ = (
        Index("ix_session_operator_notes_session_id_id", "session_id", "id"),
        Index("ix_session_operator_notes_author_created", "author_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    author_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    author_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SessionCollaborationEventRecord(Base):
    __tablename__ = "session_collaboration_events"
    __table_args__ = (
        Index("ix_session_collaboration_events_session_id_id", "session_id", "id"),
        Index("ix_session_collaboration_events_event_created", "event_kind", "created_at"),
        Index("ix_session_collaboration_events_actor_created", "actor_kind", "actor_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    automation_state_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    automation_state_after: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_operator_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_operator_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_queue_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_queue_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    related_run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True)
    related_note_id: Mapped[int | None] = mapped_column(ForeignKey("session_operator_notes.id"), nullable=True)
    related_proposal_id: Mapped[str | None] = mapped_column(ForeignKey("resource_proposals.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


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
    approval_prompt_id: Mapped[int | None] = mapped_column(ForeignKey("approval_action_prompts.id"), nullable=True)
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


class SessionMemoryRecord(Base):
    __tablename__ = "session_memories"
    __table_args__ = (
        Index("ix_session_memories_session_status_created", "session_id", "status", "created_at"),
        Index("ix_session_memories_source_message_status", "source_message_id", "status"),
        Index("ix_session_memories_source_summary_status", "source_summary_snapshot_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    memory_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    source_summary_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("summary_snapshots.id"), nullable=True)
    source_base_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    source_through_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    derivation_strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class RetrievalRecord(Base):
    __tablename__ = "retrieval_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source_kind",
            "source_id",
            "chunk_index",
            "content_hash",
            "derivation_strategy_id",
            name="uq_retrieval_records_chunk_identity",
        ),
        Index("ix_retrieval_records_session_source_created", "session_id", "source_kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    source_summary_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("summary_snapshots.id"), nullable=True)
    source_memory_id: Mapped[int | None] = mapped_column(ForeignKey("session_memories.id"), nullable=True)
    source_attachment_extraction_id: Mapped[int | None] = mapped_column(ForeignKey("attachment_extractions.id"), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ranking_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    derivation_strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AttachmentExtractionRecord(Base):
    __tablename__ = "attachment_extractions"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id",
            "extractor_kind",
            "derivation_strategy_id",
            name="uq_attachment_extractions_identity",
        ),
        Index("ix_attachment_extractions_session_status_created", "session_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("message_attachments.id"), nullable=False)
    extractor_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    derivation_strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


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
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
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
    delivery_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completion_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ApprovalActionPromptRecord(Base):
    __tablename__ = "approval_action_prompts"
    __table_args__ = (
        UniqueConstraint("approve_token_hash", name="uq_approval_action_prompts_approve_hash"),
        UniqueConstraint("deny_token_hash", name="uq_approval_action_prompts_deny_hash"),
        Index("ix_approval_action_prompts_proposal_created", "proposal_id", "created_at"),
        Index("ix_approval_action_prompts_session_status_created", "session_id", "status", "created_at"),
        Index("ix_approval_action_prompts_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("resource_proposals.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    channel_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transport_address_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approve_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deny_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ApprovalActionPromptStatus.PENDING.value)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_via: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decider_actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    presentation_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


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
    stream_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_stream_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OutboundDeliveryStreamEventRecord(Base):
    __tablename__ = "outbound_delivery_stream_events"
    __table_args__ = (
        UniqueConstraint(
            "outbound_delivery_attempt_id",
            "sequence_number",
            name="uq_outbound_delivery_stream_events_attempt_sequence",
        ),
        Index(
            "ix_outbound_delivery_stream_events_attempt_sequence",
            "outbound_delivery_attempt_id",
            "sequence_number",
        ),
        Index("ix_outbound_delivery_stream_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbound_delivery_id: Mapped[int] = mapped_column(ForeignKey("outbound_deliveries.id"), nullable=False)
    outbound_delivery_attempt_id: Mapped[int] = mapped_column(ForeignKey("outbound_delivery_attempts.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
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
