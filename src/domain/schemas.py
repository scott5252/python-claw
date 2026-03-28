from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CanonicalAttachmentInput(BaseModel):
    external_attachment_id: str | None = None
    source_url: str
    mime_type: str
    filename: str | None = None
    byte_size: int | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url", "mime_type")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must be non-empty")
        return trimmed

    @field_validator("byte_size")
    @classmethod
    def _validate_byte_size(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("byte_size must be non-negative")
        return value

    @field_validator("provider_metadata")
    @classmethod
    def _validate_provider_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, sort_keys=True)
        if len(encoded) > 2000:
            raise ValueError("provider_metadata must be 2000 characters or fewer")
        return value


class InboundMessageRequest(BaseModel):
    channel_kind: str
    channel_account_id: str
    external_message_id: str
    sender_id: str
    content: str
    peer_id: str | None = None
    group_id: str | None = None
    attachments: list[CanonicalAttachmentInput] = Field(default_factory=list)


class DurableTransportAddress(BaseModel):
    address_key: str
    provider: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("address_key", "provider")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must be non-empty")
        return trimmed

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, sort_keys=True)
        if len(encoded) > 2000:
            raise ValueError("metadata must be 2000 characters or fewer")
        return value


class InboundMessageResponse(BaseModel):
    session_id: str
    message_id: int
    run_id: str
    status: str
    dedupe_status: Literal["accepted", "duplicate"]
    trace_id: str


class ExecutionRunResponse(BaseModel):
    id: str
    session_id: str
    message_id: int | None
    agent_id: str
    model_profile_key: str
    policy_profile_key: str
    tool_profile_key: str
    trigger_kind: str
    trigger_ref: str
    lane_key: str
    status: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    worker_id: str | None
    last_error: str | None
    trace_id: str | None
    correlation_id: str | None = None
    degraded_reason: str | None = None
    failure_category: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionRunPageResponse(BaseModel):
    items: list[ExecutionRunResponse]


class SessionResponse(BaseModel):
    id: str
    session_key: str
    channel_kind: str
    channel_account_id: str
    scope_kind: str
    peer_id: str | None
    group_id: str | None
    scope_name: str
    owner_agent_id: str
    session_kind: str
    parent_session_id: str | None
    transport_address_key: str | None = None
    created_at: datetime
    last_activity_at: datetime


class MessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    external_message_id: str | None
    sender_id: str
    created_at: datetime


class MessagePageResponse(BaseModel):
    items: list[MessageResponse]
    next_before_message_id: int | None = Field(default=None)


class PendingApprovalResponse(BaseModel):
    proposal_id: str
    message_id: int
    agent_id: str
    requested_by: str
    current_state: str
    resource_kind: str
    resource_version_id: str
    capability_name: str
    typed_action_id: str
    content_hash: str
    canonical_params: dict[str, Any]
    canonical_params_json: str
    scope_kind: str
    next_action: str
    proposed_at: datetime
    pending_approval_at: datetime | None


class DependencyStatusResponse(BaseModel):
    name: str
    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    checks: list[DependencyStatusResponse] = Field(default_factory=list)


class DiagnosticsPageResponse(BaseModel):
    items: list[dict[str, Any]]
    limit: int
    next_cursor: str | None = None
    has_more: bool
    capability_status: str = "enabled"


class RunDiagnosticsResponse(BaseModel):
    run: ExecutionRunResponse
    lane_lease: dict[str, Any] | None = None
    global_lease: dict[str, Any] | None = None
    recent_failures: list[str] = Field(default_factory=list)
    correlated_artifacts: dict[str, Any] = Field(default_factory=dict)
    execution_binding: dict[str, Any] | None = None
    capability_status: str = "enabled"


class AgentProfileResponse(BaseModel):
    agent_id: str
    display_name: str
    role_kind: str
    description: str | None = None
    default_model_profile_id: int
    policy_profile_key: str
    tool_profile_key: str
    enabled: int
    created_at: datetime
    updated_at: datetime


class ModelProfileResponse(BaseModel):
    id: int
    profile_key: str
    runtime_mode: str
    provider: str | None = None
    model_name: str | None = None
    temperature: str | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int
    tool_call_mode: str
    streaming_enabled: int
    enabled: int
    base_url: str | None = None
    created_at: datetime
    updated_at: datetime


class SessionContinuityDiagnosticsResponse(BaseModel):
    session_id: str
    capability_status: str
    summary_snapshot_count: int = 0
    latest_summary_created_at: datetime | None = None
    context_manifest_count: int = 0
    latest_manifest_degraded: bool | None = None
    pending_outbox_jobs: int = 0
    failed_outbox_jobs: int = 0
    recent_run_statuses: list[str] = Field(default_factory=list)


class ProviderControlResponse(BaseModel):
    status: str
    detail: str | None = None


class WebchatInboundRequest(BaseModel):
    actor_id: str
    content: str
    message_id: str | None = None
    peer_id: str | None = None
    group_id: str | None = None
    stream_id: str | None = None
    attachments: list[CanonicalAttachmentInput] = Field(default_factory=list)


class WebchatInboundResponse(InboundMessageResponse):
    external_message_id: str


class WebchatDeliveryPollItem(BaseModel):
    delivery_id: int
    status: str
    delivery_kind: str
    provider_message_id: str | None = None
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class WebchatDeliveryPollResponse(BaseModel):
    items: list[WebchatDeliveryPollItem]
    next_after_delivery_id: int | None = None


class WebchatStreamEventPayload(BaseModel):
    event_id: int
    delivery_id: int
    attempt_id: int
    sequence_number: int
    event_kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
