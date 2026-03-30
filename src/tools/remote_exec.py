from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition, validation_error_from_pydantic

RESERVED_REMOTE_EXEC_KEYS = frozenset({"tool_call_id", "execution_attempt_number"})


def _extract_template_vars(argv_template: list[str]) -> list[str]:
    seen: list[str] = []
    for item in argv_template:
        for var in re.findall(r'\{(\w+)\}', item):
            if var not in seen:
                seen.append(var)
    return seen


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

    # Build dynamic schema from agent's argv_template variable placeholders
    template_vars: list[str] = []
    runtime = context.runtime_services.remote_execution_runtime
    if runtime is not None and hasattr(runtime, "settings"):
        agent_template = runtime.settings.get_remote_exec_template_for_agent(context.agent_id)
        if agent_template is not None:
            template_vars = _extract_template_vars(agent_template.argv_template)

    if template_vars:
        provider_input_schema: dict[str, object] = {
            "type": "object",
            "description": "Arguments for the remote command template. Provide all required parameters.",
            "properties": {
                var: {"type": "string", "description": f"Value for the `{var}` template parameter"}
                for var in template_vars
            },
            "required": template_vars,
            "additionalProperties": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
        }
    else:
        provider_input_schema = {
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
        }

    return ToolDefinition(
        capability_name="remote_exec",
        description="Run an approved command on the node runner.",
        input_schema=RemoteExecRequest,
        tool_schema_name="remote_exec.invocation",
        schema_version="1.0",
        usage_guidance=(
            "Use when the user wants an approved command or external action to run. "
            "If approval is still needed, call this tool anyway so the backend can create the proposal. "
            "Do not ask in plain text whether a proposal should be created. "
            "Provide a flat JSON object with scalar values matching the command template parameters. "
            "The argument keys must match the template variable names defined for this agent."
        ),
        provider_input_schema=provider_input_schema,
        validate=validate,
        canonicalize=canonicalize,
        invoke=invoke,
    )
