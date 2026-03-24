from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.execution.contracts import (
    NodeCommandTemplate,
    NodeExecutionResult,
    RemoteInvocation,
    SignedNodeExecRequest,
    build_exec_request,
    derive_argv,
)
from src.policies.service import ApprovalMatch, canonicalize_params, hash_payload
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
        template = NodeCommandTemplate.from_payload(json.loads(version.resource_payload))
        invocation = RemoteInvocation(
            arguments=arguments,
            env={},
            working_dir=template.working_dir,
            timeout_seconds=template.timeout_seconds,
        )
        if hash_payload(canonicalize_params(arguments)) != approval.canonical_params_hash:
            raise PermissionError("missing exact approval for requested action")
        sandbox = self.sandbox_service.resolve(
            db,
            agent_id=agent_id,
            session_id=session_id,
            template=template,
        )
        request = build_exec_request(
            execution_run_id=execution_run_id,
            tool_call_id=tool_call_id,
            execution_attempt_number=execution_attempt_number,
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            approval_id=approval.approval_id,
            resource_version_id=approval.resource_version_id,
            resource_payload_hash=version.content_hash,
            invocation=invocation,
            argv=derive_argv(template=template, arguments=arguments),
            sandbox_mode=sandbox.sandbox_mode,
            sandbox_key=sandbox.sandbox_key,
            workspace_root=sandbox.workspace_root,
            workspace_mount_mode=sandbox.workspace_mount_mode,
            typed_action_id=approval.typed_action_id,
            ttl_seconds=self.settings.node_runner_request_ttl_seconds,
        )
        signed = self.signing_service.build_signed_request(
            key_id=self.settings.node_runner_signing_key_id,
            request_payload=request.to_payload(),
        )
        return self.runner_client(db, signed)
