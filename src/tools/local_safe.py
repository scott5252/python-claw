from __future__ import annotations

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition


def create_echo_text_tool(context: ToolRuntimeContext) -> ToolDefinition:
    _ = context

    def invoke(arguments: dict[str, str]) -> ToolResultPayload:
        text = arguments.get("text", "")
        return ToolResultPayload(content=text, metadata={"echoed": True})

    return ToolDefinition(
        capability_name="echo_text",
        description="Echo the provided text back to the runtime.",
        invoke=invoke,
    )
