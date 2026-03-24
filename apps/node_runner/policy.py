from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.db.models import NodeExecutionAuditRecord, NodeExecutionStatus
from src.execution.audit import ExecutionAuditRepository
from src.execution.contracts import (
    NodeCommandTemplate,
    NodeExecRequest,
    SignedNodeExecRequest,
    derive_argv,
)
from src.policies.service import hash_payload
from src.sandbox.service import SandboxService
from src.security.signing import SigningService


SHELL_WRAPPERS = {"sh", "bash", "zsh", "/bin/sh", "/bin/bash", "/bin/zsh"}


@dataclass(frozen=True)
class PolicyDecision:
    record: NodeExecutionAuditRecord
    should_execute: bool


@dataclass
class NodeRunnerPolicy:
    settings: Settings
    signing_service: SigningService
    capabilities_repository: CapabilitiesRepository
    sandbox_service: SandboxService
    audit_repository: ExecutionAuditRepository

    def authorize(self, db: Session, *, signed_request: SignedNodeExecRequest) -> PolicyDecision:
        request = signed_request.request
        record, created = self.audit_repository.insert_or_get(db, request=request)
        if not self.signing_service.verify(
            key_id=signed_request.key_id,
            request_payload=request.to_payload(),
            signature=signed_request.signature,
        ):
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="signature verification failed"),
                should_execute=False,
            )
        if datetime.fromisoformat(request.expires_at) <= datetime.fromisoformat(request.issued_at):
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="invalid freshness window"),
                should_execute=False,
            )
        if datetime.fromisoformat(request.expires_at) <= datetime.now(datetime.fromisoformat(request.expires_at).tzinfo):
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="request expired"),
                should_execute=False,
            )
        if not created:
            if record.status in {
                NodeExecutionStatus.RECEIVED.value,
                NodeExecutionStatus.RUNNING.value,
                NodeExecutionStatus.REJECTED.value,
                NodeExecutionStatus.COMPLETED.value,
                NodeExecutionStatus.FAILED.value,
                NodeExecutionStatus.TIMED_OUT.value,
            }:
                if (
                    record.command_fingerprint != hash_payload("|".join(request.argv))
                    or record.workspace_root != request.workspace_root
                    or record.workspace_mount_mode != request.workspace_mount_mode
                ):
                    return PolicyDecision(
                        record=self.audit_repository.mark_rejected(db, record=record, reason="request replay payload mismatch"),
                        should_execute=False,
                    )
                return PolicyDecision(record=record, should_execute=False)

        version = self.capabilities_repository.get_resource_version(db, resource_version_id=request.resource_version_id)
        if version is None:
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="resource version not found"),
                should_execute=False,
            )
        template = NodeCommandTemplate.from_payload(json.loads(version.resource_payload))
        recomputed_argv = derive_argv(
            template=template,
            arguments=json.loads(request.canonical_params_json)["arguments"],
        )
        if request.argv != recomputed_argv:
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="derived argv mismatch"),
                should_execute=False,
            )
        if request.resource_payload_hash != hash_payload(version.resource_payload):
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="resource payload hash mismatch"),
                should_execute=False,
            )
        if request.argv[0] in SHELL_WRAPPERS:
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="shell wrappers are denied"),
                should_execute=False,
            )
        allowed = {item.strip() for item in self.settings.node_runner_allowed_executables.split(",") if item.strip()}
        if request.argv[0] not in allowed:
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="executable is not allowlisted"),
                should_execute=False,
            )
        sandbox = self.sandbox_service.resolve(
            db,
            agent_id=request.agent_id,
            session_id=request.session_id,
            template=template,
        )
        if (
            sandbox.sandbox_mode != request.sandbox_mode
            or sandbox.sandbox_key != request.sandbox_key
            or sandbox.workspace_root != request.workspace_root
            or sandbox.workspace_mount_mode != request.workspace_mount_mode
        ):
            return PolicyDecision(
                record=self.audit_repository.mark_rejected(db, record=record, reason="sandbox resolution mismatch"),
                should_execute=False,
            )
        return PolicyDecision(record=record, should_execute=True)
