from __future__ import annotations

from src.graphs.state import AssistantState, PromptPayload, PromptToolDefinition
from src.tools.registry import ToolDefinition
from src.tools.typed_actions import get_typed_action


PROMPT_STRATEGY_ID = "provider-runtime-v1"


def _argument_guidance(capability_name: str) -> dict[str, str]:
    if capability_name in {"echo_text", "send_message"}:
        return {"text": "string"}
    if capability_name == "remote_exec":
        return {
            "command": "string",
            "tool_call_id": "string optional",
            "execution_attempt_number": "integer optional",
        }
    return {}


def _governance_hint(capability_name: str) -> str | None:
    typed_action = get_typed_action(capability_name)
    if typed_action is None or not typed_action.requires_approval:
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
            argument_guidance=_argument_guidance(tool.capability_name),
            requires_approval=bool(get_typed_action(tool.capability_name) and get_typed_action(tool.capability_name).requires_approval),
            governance_hint=_governance_hint(tool.capability_name),
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
