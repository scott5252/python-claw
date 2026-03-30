from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.db.models import ExecutionRunRecord
from src.execution.contracts import (
    NodeCommandTemplate,
    NodeExecutionResult,
    RemoteInvocation,
    SignedNodeExecRequest,
    build_exec_request,
    derive_argv,
)
from src.policies.service import ApprovalMatch, build_approval_identity_hash, canonicalize_params, default_tool_schema_identity
from src.sandbox.service import SandboxService
from src.security.signing import SigningService


@dataclass
class RemoteExecutionRuntime:
    settings: Settings
    capabilities_repository: CapabilitiesRepository
    sandbox_service: SandboxService
    signing_service: SigningService
    runner_client: Callable[[Session, SignedNodeExecRequest], NodeExecutionResult]

    def execute(
        self,
        db: Session,
        *,
        approval: ApprovalMatch,
        session_id: str,
        message_id: int,
        agent_id: str,
        execution_run_id: str,
        tool_call_id: str,
        execution_attempt_number: int,
        arguments: dict[str, object],
    ) -> NodeExecutionResult:
        version = self.capabilities_repository.get_resource_version(db, resource_version_id=approval.resource_version_id)
        if version is None:
            raise RuntimeError("approved resource version not found")

        version_payload = json.loads(version.resource_payload)

        # If the version is a governance proposal payload (no 'executable'), look up the agent's NodeCommandTemplate
        if "executable" not in version_payload:
            template_version = self.capabilities_repository.find_active_node_command_template_version(db, agent_id=agent_id)
            if template_version is None:
                raise RuntimeError(
                    f"no NodeCommandTemplate registered for agent {agent_id!r}; "
                    "configure PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES"
                )
            template = NodeCommandTemplate.from_payload(json.loads(template_version.resource_payload))
            effective_version = template_version
        else:
            template = NodeCommandTemplate.from_payload(version_payload)
            effective_version = version

        invocation = RemoteInvocation(
            arguments=arguments,
            env={},
            working_dir=template.working_dir,
            timeout_seconds=template.timeout_seconds,
        )
        tool_schema_name = version_payload.get("tool_schema_name", default_tool_schema_identity("remote_exec")[0])
        tool_schema_version = version_payload.get("tool_schema_version", default_tool_schema_identity("remote_exec")[1])
        if build_approval_identity_hash(
            tool_schema_name=tool_schema_name,
            tool_schema_version=tool_schema_version,
            canonical_arguments_json=canonicalize_params(arguments),
        ) != approval.canonical_params_hash:
            raise PermissionError("missing exact approval for requested action")
        sandbox = self.sandbox_service.resolve(
            db,
            agent_id=agent_id,
            session_id=session_id,
            template=template,
        )
        run = db.get(ExecutionRunRecord, execution_run_id)
        request = build_exec_request(
            execution_run_id=execution_run_id,
            tool_call_id=tool_call_id,
            execution_attempt_number=execution_attempt_number,
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            approval_id=approval.approval_id,
            resource_version_id=effective_version.id,
            resource_payload_hash=effective_version.content_hash,
            invocation=invocation,
            argv=derive_argv(template=template, arguments=arguments),
            sandbox_mode=sandbox.sandbox_mode,
            sandbox_key=sandbox.sandbox_key,
            workspace_root=sandbox.workspace_root,
            workspace_mount_mode=sandbox.workspace_mount_mode,
            typed_action_id=approval.typed_action_id,
            ttl_seconds=self.settings.node_runner_request_ttl_seconds,
            trace_id=None if run is None else run.trace_id,
        )
        signed = self.signing_service.build_signed_request(
            key_id=self.settings.node_runner_signing_key_id,
            request_payload=request.to_payload(),
        )
        return self.runner_client(db, signed)
