from __future__ import annotations

from src.graphs.state import OutboundIntent, ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition


def create_send_message_tool(context: ToolRuntimeContext) -> ToolDefinition:
    def invoke(arguments: dict[str, str]) -> ToolResultPayload:
        text = arguments.get("text", "").strip()
        return ToolResultPayload(
            content=f"Prepared outbound message: {text}",
            outbound_intent=OutboundIntent(
                text=text,
                channel_kind=context.channel_kind,
                sender_id=context.sender_id,
            ),
        )

    return ToolDefinition(
        capability_name="send_message",
        description="Create a runtime-owned outbound intent without calling a transport.",
        invoke=invoke,
    )
