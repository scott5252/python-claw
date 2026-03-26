from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition, validation_error_from_pydantic


class EchoTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


def create_echo_text_tool(context: ToolRuntimeContext) -> ToolDefinition:
    _ = context

    def validate(arguments: dict[str, object]) -> EchoTextRequest:
        try:
            return EchoTextRequest.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error_from_pydantic(capability_name="echo_text", exc=exc) from exc

    def canonicalize(request: EchoTextRequest) -> dict[str, str]:
        return request.model_dump(mode="json", round_trip=True)

    def invoke(request: EchoTextRequest) -> ToolResultPayload:
        return ToolResultPayload(content=request.text, metadata={"echoed": True})

    return ToolDefinition(
        capability_name="echo_text",
        description="Echo the provided text back to the runtime.",
        input_schema=EchoTextRequest,
        tool_schema_name="echo_text.input",
        schema_version="1.0",
        usage_guidance="Use when you need the runtime to repeat a provided text string verbatim.",
        provider_input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back to the runtime.",
                }
            },
            "required": ["text"],
        },
        validate=validate,
        canonicalize=canonicalize,
        invoke=invoke,
    )
