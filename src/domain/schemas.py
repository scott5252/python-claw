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

class InboundMessageResponse(BaseModel):
    session_id: str
    message_id: int
    run_id: str
    status: str
    dedupe_status: Literal["accepted", "duplicate"]


class ExecutionRunResponse(BaseModel):
    id: str
    session_id: str
    message_id: int | None
    agent_id: str
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
