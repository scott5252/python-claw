from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from src.graphs.state import OutboundIntent, ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition, validation_error_from_pydantic


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty after trimming")
        return value


def create_send_message_tool(context: ToolRuntimeContext) -> ToolDefinition:
    def validate(arguments: dict[str, object]) -> SendMessageRequest:
        try:
            return SendMessageRequest.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error_from_pydantic(capability_name="send_message", exc=exc) from exc

    def canonicalize(request: SendMessageRequest) -> dict[str, str]:
        return {"text": request.text}

    def invoke(request: SendMessageRequest) -> ToolResultPayload:
        text = request.text.strip()
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
        input_schema=SendMessageRequest,
        tool_schema_name="send_message.input",
        schema_version="1.0",
        usage_guidance="Use to prepare one outbound message with a required text string.",
        provider_input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Message text to send through the runtime-owned outbound path.",
                }
            },
            "required": ["text"],
        },
        validate=validate,
        canonicalize=canonicalize,
        invoke=invoke,
    )
