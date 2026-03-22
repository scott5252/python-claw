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
