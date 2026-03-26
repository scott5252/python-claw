from __future__ import annotations

from src.graphs.state import AssistantState, PromptPayload, PromptToolDefinition
from src.tools.registry import ToolDefinition


PROMPT_STRATEGY_ID = "provider-runtime-v1"

def _governance_hint(tool: ToolDefinition) -> str | None:
    if not tool.requires_approval:
        return None
    return "This capability requires an exact backend approval before it can execute."


def _build_context_sections(*, state: AssistantState) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    if state.summary_context is not None:
        sections.append(
            {
                "kind": "summary",
                "snapshot_id": state.summary_context.snapshot_id,
                "content": state.summary_context.summary_text,
                "base_message_id": state.summary_context.base_message_id,
                "through_message_id": state.summary_context.through_message_id,
            }
        )
    if state.memory_items:
        sections.append(
            {
                "kind": "memory",
                "items": [
                    {
                        "memory_id": item.memory_id,
                        "memory_kind": item.memory_kind,
                        "content": item.content_text,
                        "source_kind": item.source_kind,
                        "confidence": item.confidence,
                    }
                    for item in state.memory_items
                ],
            }
        )
    if state.retrieval_items:
        sections.append(
            {
                "kind": "retrieval",
                "items": [
                    {
                        "retrieval_id": item.retrieval_id,
                        "source_kind": item.source_kind,
                        "source_id": item.source_id,
                        "content": item.content_text,
                        "score": item.score,
                    }
                    for item in state.retrieval_items
                ],
            }
        )
    if state.attachment_items:
        sections.append(
            {
                "kind": "attachment_content",
                "items": [
                    {
                        "attachment_id": item.attachment_id,
                        "extraction_id": item.extraction_id,
                        "filename": item.filename,
                        "mime_type": item.mime_type,
                        "content": item.content_text,
                        "metadata": item.metadata,
                    }
                    for item in state.attachment_items
                ],
            }
        )
    if state.attachment_fallbacks:
        sections.append(
            {
                "kind": "attachment_metadata_fallback",
                "items": [
                    {
                        "attachment_id": item.attachment_id,
                        "filename": item.filename,
                        "mime_type": item.mime_type,
                        "storage_key": item.storage_key,
                        "status": item.status,
                        "reason": item.reason,
                    }
                    for item in state.attachment_fallbacks
                ],
            }
        )
    return sections


def build_prompt_payload(*, state: AssistantState, visible_tools: list[ToolDefinition], tool_call_mode: str) -> PromptPayload:
    conversation = [
        {
            "role": message.role,
            "content": message.content,
            "sender_id": message.sender_id,
        }
        for message in state.messages
    ]
    conversation.append({"role": "user", "content": state.user_text, "sender_id": state.sender_id})

    tools = [
        PromptToolDefinition(
            name=tool.capability_name,
            description=tool.description,
            usage_guidance=tool.usage_guidance,
            input_schema=tool.provider_input_schema,
            tool_schema_name=tool.tool_schema_name,
            schema_version=tool.schema_version,
            requires_approval=tool.requires_approval,
            governance_hint=_governance_hint(tool),
        )
        for tool in visible_tools
    ]

    return PromptPayload(
        system_instructions=(
            "You are the assistant runtime for python-claw. Respond helpfully and concisely. "
            "Use tools only when they are necessary and only with arguments that match the backend guidance. "
            "Treat transcript messages as canonical; summary, memory, retrieval, and attachment sections are additive context only."
        ),
        conversation=conversation,
        attachments=list(state.context_manifest.get("attachments", [])),
        context_sections=_build_context_sections(state=state),
        tools=tools,
        approval_guidance=(
            "Backend policy and approval checks are authoritative. If a tool requires approval, "
            "the backend may create a proposal instead of executing it."
        ),
        response_contract=(
            "Return either plain assistant text, or structured tool requests that map cleanly onto "
            "backend tool names and JSON-object arguments."
        ),
        metadata={
            "prompt_strategy_id": PROMPT_STRATEGY_ID,
            "tool_call_mode": tool_call_mode,
            "degraded": state.degraded,
        },
    )
