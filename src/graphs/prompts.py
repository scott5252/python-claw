from __future__ import annotations

from src.graphs.state import AssistantState, PromptPayload, PromptToolDefinition
from src.tools.registry import ToolDefinition


PROMPT_STRATEGY_ID = "provider-runtime-v1"

def _governance_hint(tool: ToolDefinition) -> str | None:
    if not tool.requires_approval:
        return None
    return "This capability requires an exact backend approval before it can execute."


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
            "Use tools only when they are necessary and only with arguments that match the backend guidance."
        ),
        conversation=conversation,
        attachments=list(state.context_manifest.get("attachments", [])),
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
