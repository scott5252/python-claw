from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition, ToolExecutionError, validation_error_from_pydantic


def _format_delegation_queued_message(*, child_agent_id: str, delegation_id: str, task_text: str, expected_output: str | None) -> str:
    lines = [f"Queued bounded delegation to `{child_agent_id}` as `{delegation_id}`.", "", "Requested work:", task_text]
    if expected_output and expected_output.strip():
        lines.extend(["", "Expected output:", expected_output.strip()])
    return "\n".join(lines)


class DelegateToAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_agent_id: str
    task_text: str
    delegation_kind: str
    expected_output: str | None = None
    notes: str | None = None

    @field_validator("child_agent_id", "task_text", "delegation_kind")
    @classmethod
    def _require_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must be non-empty")
        return trimmed


def create_delegate_to_agent_tool(context: ToolRuntimeContext) -> ToolDefinition:
    def validate(arguments: dict[str, object]) -> DelegateToAgentRequest:
        try:
            return DelegateToAgentRequest.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error_from_pydantic(capability_name="delegate_to_agent", exc=exc) from exc

    def canonicalize(request: DelegateToAgentRequest) -> dict[str, str | None]:
        return request.model_dump(mode="json", round_trip=True)

    def invoke(request: DelegateToAgentRequest) -> ToolResultPayload:
        delegation_service = context.runtime_services.delegation_service
        db = context.runtime_services.db
        execution_run_id = context.runtime_services.execution_run_id
        policy_service = context.runtime_services.policy_service
        if delegation_service is None or db is None or execution_run_id is None or policy_service is None:
            raise ToolExecutionError("delegation runtime service unavailable")
        result = delegation_service.create_delegation(
            db,
            policy_service=policy_service,
            parent_session_id=context.session_id,
            parent_message_id=context.message_id,
            parent_run_id=execution_run_id,
            parent_agent_id=context.agent_id,
            parent_policy_profile_key=context.policy_profile_key,
            parent_tool_profile_key=context.tool_profile_key,
            correlation_id=str(
                context.policy_context.get("current_tool_correlation_id")
                or f"tool:{execution_run_id}:{context.message_id}:{request.child_agent_id}:{request.delegation_kind}"
            ),
            child_agent_id=request.child_agent_id,
            task_text=request.task_text,
            delegation_kind=request.delegation_kind,
            expected_output=request.expected_output,
            notes=request.notes,
        )
        return ToolResultPayload(
            content=_format_delegation_queued_message(
                child_agent_id=request.child_agent_id,
                delegation_id=result.delegation_id,
                task_text=request.task_text,
                expected_output=request.expected_output,
            ),
            metadata={
                "delegation_id": result.delegation_id,
                "child_session_id": result.child_session_id,
                "child_run_id": result.child_run_id,
                "child_agent_id": result.child_agent_id,
                "status": result.status,
                "asynchronous": True,
            },
        )

    return ToolDefinition(
        capability_name="delegate_to_agent",
        description="Queue asynchronous bounded work for an allowed child agent.",
        input_schema=DelegateToAgentRequest,
        tool_schema_name="delegate_to_agent.input",
        schema_version="1.0",
        usage_guidance=(
            "Use when a bounded subtask should be delegated to an allowed specialist agent. "
            "Delegation is asynchronous; do not wait for the child result in the same turn."
        ),
        provider_input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "child_agent_id": {"type": "string"},
                "task_text": {"type": "string"},
                "delegation_kind": {"type": "string"},
                "expected_output": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["child_agent_id", "task_text", "delegation_kind"],
        },
        validate=validate,
        canonicalize=canonicalize,
        invoke=invoke,
    )
