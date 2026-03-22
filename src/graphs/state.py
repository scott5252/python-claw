from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class ToolEvent:
    correlation_id: str
    capability_name: str
    status: str
    arguments: dict[str, Any]
    outcome: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True)
class OutboundIntent:
    text: str
    channel_kind: str
    sender_id: str


@dataclass(frozen=True)
class ToolResultPayload:
    content: str
    outbound_intent: OutboundIntent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTurnResult:
    needs_tools: bool
    tool_requests: list[ToolRequest]
    response_text: str


@dataclass(frozen=True)
class ToolRuntimeServices:
    clock: Any | None = None


@dataclass(frozen=True)
class ToolRuntimeContext:
    session_id: str
    agent_id: str
    channel_kind: str
    sender_id: str
    policy_context: dict[str, Any]
    runtime_services: ToolRuntimeServices


@dataclass
class AssistantState:
    session_id: str
    agent_id: str
    channel_kind: str
    sender_id: str
    user_text: str
    messages: list[ConversationMessage]
    tool_events: list[ToolEvent] = field(default_factory=list)
    response_text: str = ""
    needs_tools: bool = False
