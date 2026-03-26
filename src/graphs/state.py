from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.tools.registry import ToolDefinition


@dataclass(frozen=True)
class PromptToolDefinition:
    name: str
    description: str
    usage_guidance: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    tool_schema_name: str = ""
    schema_version: str = ""
    requires_approval: bool = False
    governance_hint: str | None = None


@dataclass(frozen=True)
class PromptPayload:
    system_instructions: str
    conversation: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    tools: list[PromptToolDefinition]
    approval_guidance: str
    response_contract: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str
    sender_id: str


@dataclass(frozen=True)
class ToolRequest:
    correlation_id: str
    capability_name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolEvent:
    correlation_id: str
    capability_name: str
    status: str
    arguments: dict[str, Any]
    outcome: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundIntent:
    text: str
    channel_kind: str
    sender_id: str
    media_refs: list[str] = field(default_factory=list)
    reply_to_external_id: str | None = None


@dataclass(frozen=True)
class ToolResultPayload:
    content: str
    outbound_intent: OutboundIntent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RejectedToolRequest:
    correlation_id: str
    capability_name: str | None
    arguments: dict[str, Any]
    error: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolValidationIssue:
    field_path: str
    message: str


@dataclass(frozen=True)
class ValidatedToolCall:
    correlation_id: str
    capability_name: str
    tool_schema_name: str
    schema_version: str
    typed_action_id: str | None
    requires_approval: bool
    raw_arguments: dict[str, Any]
    validated_request: Any
    canonical_arguments: dict[str, Any]
    canonical_arguments_json: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTurnResult:
    needs_tools: bool
    tool_requests: list[ToolRequest]
    response_text: str
    execution_metadata: dict[str, Any] = field(default_factory=dict)
    rejected_tool_requests: list[RejectedToolRequest] = field(default_factory=list)


@dataclass(frozen=True)
class ToolRuntimeServices:
    clock: Any | None = None
    db: Any | None = None
    execution_run_id: str | None = None
    remote_execution_runtime: Any | None = None
    policy_service: Any | None = None


@dataclass(frozen=True)
class ToolRuntimeContext:
    session_id: str
    message_id: int
    agent_id: str
    channel_kind: str
    sender_id: str
    policy_context: dict[str, Any]
    runtime_services: ToolRuntimeServices


@dataclass
class AssistantState:
    session_id: str
    message_id: int
    agent_id: str
    channel_kind: str
    sender_id: str
    user_text: str
    messages: list[ConversationMessage]
    context_manifest: dict[str, Any] = field(default_factory=dict)
    llm_prompt: PromptPayload | None = None
    degraded: bool = False
    tool_events: list[ToolEvent] = field(default_factory=list)
    response_text: str = ""
    assistant_message_id: int | None = None
    needs_tools: bool = False
    awaiting_approval: bool = False
    bound_tools: dict[str, ToolDefinition] = field(default_factory=dict)
