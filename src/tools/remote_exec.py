from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition, validation_error_from_pydantic

RESERVED_REMOTE_EXEC_KEYS = frozenset({"tool_call_id", "execution_attempt_number"})


class RemoteExecRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def validate_open_key_scalar_map(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("arguments must be a JSON object")
        for key, item in value.items():
            if key in RESERVED_REMOTE_EXEC_KEYS:
                raise ValueError(f"{key} is reserved for backend runtime metadata")
            if not isinstance(key, str):
                raise ValueError("argument keys must be strings")
            if isinstance(item, (dict, list)):
                raise ValueError(f"{key} must be a JSON scalar value")
            if not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError(f"{key} must be a JSON scalar value")
        return value


def create_remote_exec_tool(context: ToolRuntimeContext) -> ToolDefinition:
    def validate(arguments: dict[str, object]) -> RemoteExecRequest:
        try:
            return RemoteExecRequest.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error_from_pydantic(capability_name="remote_exec", exc=exc) from exc

    def canonicalize(request: RemoteExecRequest) -> dict[str, object]:
        return request.model_dump(mode="json", round_trip=True)

    def invoke(request: RemoteExecRequest) -> ToolResultPayload:
        runtime = context.runtime_services.remote_execution_runtime
        policy_service = context.runtime_services.policy_service
        db = context.runtime_services.db
        execution_run_id = context.runtime_services.execution_run_id
        if runtime is None or policy_service is None or db is None or execution_run_id is None:
            raise RuntimeError("remote execution runtime is unavailable")
        arguments = canonicalize(request)
        approval = policy_service.get_matching_approval(
            context=context,
            call=context.policy_context["validated_call"],
        )
        if approval is None:
            raise PermissionError("remote execution requires approval")
        result = runtime.execute(
            db,
            approval=approval,
            session_id=context.session_id,
            message_id=context.message_id,
            agent_id=context.agent_id,
            execution_run_id=execution_run_id,
            tool_call_id=f"{context.session_id}:{context.message_id}:remote_exec",
            execution_attempt_number=1,
            arguments=arguments,
        )
        if result.status != "completed":
            raise RuntimeError(result.deny_reason or result.stderr_preview or "remote execution failed")
        return ToolResultPayload(
            content=result.stdout_preview.strip(),
            metadata={
                "request_id": result.request_id,
                "exit_code": result.exit_code,
                "stderr_preview": result.stderr_preview,
            },
        )

    return ToolDefinition(
        capability_name="remote_exec",
        description="Run an approved command on the node runner.",
        input_schema=RemoteExecRequest,
        tool_schema_name="remote_exec.invocation",
        schema_version="1.0",
        usage_guidance=(
            "Use only with approval-relevant invocation arguments. Provide a flat JSON object with scalar values only."
        ),
        provider_input_schema={
            "type": "object",
            "description": "Flat invocation arguments for an approved remote command template.",
            "additionalProperties": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
            "properties": {},
        },
        validate=validate,
        canonicalize=canonicalize,
        invoke=invoke,
    )
