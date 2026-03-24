from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.models import (
    ActiveResourceRecord,
    AgentSandboxProfileRecord,
    ResourceApprovalRecord,
    ResourceProposalRecord,
    ResourceVersionRecord,
)
from src.policies.service import canonicalize_params, hash_payload


@dataclass
class CapabilitiesRepository:
    def get_resource_version(self, db: Session, *, resource_version_id: str) -> ResourceVersionRecord | None:
        return db.get(ResourceVersionRecord, resource_version_id)

    def get_agent_sandbox_profile(self, db: Session, *, agent_id: str) -> AgentSandboxProfileRecord | None:
        return db.query(AgentSandboxProfileRecord).filter(AgentSandboxProfileRecord.agent_id == agent_id).one_or_none()

    def upsert_agent_sandbox_profile(
        self,
        db: Session,
        *,
        agent_id: str,
        default_mode: str,
        shared_profile_key: str,
        allow_off_mode: bool,
        max_timeout_seconds: int,
    ) -> AgentSandboxProfileRecord:
        record = self.get_agent_sandbox_profile(db, agent_id=agent_id)
        if record is None:
            record = AgentSandboxProfileRecord(
                agent_id=agent_id,
                default_mode=default_mode,
                shared_profile_key=shared_profile_key,
                allow_off_mode=allow_off_mode,
                max_timeout_seconds=max_timeout_seconds,
            )
            db.add(record)
        else:
            record.default_mode = default_mode
            record.shared_profile_key = shared_profile_key
            record.allow_off_mode = allow_off_mode
            record.max_timeout_seconds = max_timeout_seconds
        db.flush()
        return record

    def create_remote_exec_capability(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        agent_id: str,
        requested_by: str,
        approver_id: str,
        template_payload: dict,
        invocation_arguments: dict,
    ) -> tuple[ResourceProposalRecord, ResourceVersionRecord, ResourceApprovalRecord, ActiveResourceRecord]:
        proposal = ResourceProposalRecord(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            resource_kind="node_command_template",
            requested_by=requested_by,
            current_state="approved",
            proposed_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc),
        )
        db.add(proposal)
        db.flush()
        version_payload = json.dumps(template_payload, sort_keys=True, separators=(",", ":"))
        version = ResourceVersionRecord(
            proposal_id=proposal.id,
            version_number=1,
            content_hash=hash_payload(version_payload),
            resource_payload=version_payload,
        )
        db.add(version)
        db.flush()
        proposal.latest_version_id = version.id
        canonical_params_json = canonicalize_params(invocation_arguments)
        approval = ResourceApprovalRecord(
            proposal_id=proposal.id,
            resource_version_id=version.id,
            approval_packet_hash=hash_payload(f"{proposal.id}:{version.id}:{canonical_params_json}"),
            typed_action_id=template_payload["typed_action_id"],
            canonical_params_json=canonical_params_json,
            canonical_params_hash=hash_payload(canonical_params_json),
            scope_kind="session_agent",
            approver_id=approver_id,
            approved_at=datetime.now(timezone.utc),
        )
        db.add(approval)
        db.flush()
        active = ActiveResourceRecord(
            proposal_id=proposal.id,
            resource_version_id=version.id,
            typed_action_id=approval.typed_action_id,
            canonical_params_hash=approval.canonical_params_hash,
            activation_state="active",
            activated_at=datetime.now(timezone.utc),
        )
        db.add(active)
        db.flush()
        return proposal, version, approval, active
