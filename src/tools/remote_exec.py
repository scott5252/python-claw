from __future__ import annotations

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.tools.registry import ToolDefinition


def create_remote_exec_tool(context: ToolRuntimeContext) -> ToolDefinition:
    def invoke(arguments: dict[str, object]) -> ToolResultPayload:
        runtime = context.runtime_services.remote_execution_runtime
        policy_service = context.runtime_services.policy_service
        db = context.runtime_services.db
        execution_run_id = context.runtime_services.execution_run_id
        if runtime is None or policy_service is None or db is None or execution_run_id is None:
            raise RuntimeError("remote execution runtime is unavailable")
        approval = policy_service.assert_execution_allowed(
            context=context,
            capability_name="remote_exec",
            arguments={key: value for key, value in arguments.items() if key not in {"tool_call_id", "execution_attempt_number"}},
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
            tool_call_id=str(arguments.get("tool_call_id", "remote-exec")),
            execution_attempt_number=int(arguments.get("execution_attempt_number", 1)),
            arguments={key: value for key, value in arguments.items() if key not in {"tool_call_id", "execution_attempt_number"}},
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
        invoke=invoke,
    )
