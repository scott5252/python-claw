from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import (
    ActiveResourceRecord,
    GovernanceTranscriptEventRecord,
    MessageRecord,
    ResourceApprovalRecord,
    ResourceProposalRecord,
    ResourceVersionRecord,
    SessionArtifactRecord,
    SessionRecord,
)
from src.graphs.state import ConversationMessage, ToolEvent, ToolRequest
from src.policies.service import canonicalize_params, hash_payload
from src.routing.service import RoutingResult
from src.tools.typed_actions import get_typed_action


class SessionRepository:
    def get_or_create_session(self, db: Session, routing: RoutingResult) -> SessionRecord:
        session = db.scalar(select(SessionRecord).where(SessionRecord.session_key == routing.session_key))
        if session is not None:
            return session

        session = SessionRecord(
            session_key=routing.session_key,
            channel_kind=routing.channel_kind,
            channel_account_id=routing.channel_account_id,
            scope_kind=routing.scope_kind,
            peer_id=routing.peer_id,
            group_id=routing.group_id,
            scope_name=routing.scope_name,
        )
        db.add(session)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            session = db.scalar(select(SessionRecord).where(SessionRecord.session_key == routing.session_key))
            if session is None:
                raise
        return session

    def get_session(self, db: Session, session_id: str) -> SessionRecord | None:
        return db.get(SessionRecord, session_id)

    def append_message(
        self,
        db: Session,
        session: SessionRecord,
        *,
        role: str,
        content: str,
        external_message_id: str | None,
        sender_id: str,
        last_activity_at: datetime,
    ) -> MessageRecord:
        message = MessageRecord(
            session_id=session.id,
            role=role,
            content=content,
            external_message_id=external_message_id,
            sender_id=sender_id,
        )
        db.add(message)
        session.last_activity_at = last_activity_at
        db.flush()
        return message

    def append_artifact(
        self,
        db: Session,
        *,
        session_id: str,
        artifact_kind: str,
        correlation_id: str,
        capability_name: str | None,
        status: str | None,
        payload: dict[str, Any],
    ) -> SessionArtifactRecord:
        artifact = SessionArtifactRecord(
            session_id=session_id,
            artifact_kind=artifact_kind,
            correlation_id=correlation_id,
            capability_name=capability_name,
            status=status,
            payload_json=json.dumps(payload, sort_keys=True),
        )
        db.add(artifact)
        db.flush()
        return artifact

    def append_tool_proposal(self, db: Session, *, session_id: str, request: ToolRequest) -> SessionArtifactRecord:
        return self.append_artifact(
            db,
            session_id=session_id,
            artifact_kind="tool_proposal",
            correlation_id=request.correlation_id,
            capability_name=request.capability_name,
            status="requested",
            payload={"arguments": request.arguments},
        )

    def append_tool_event(self, db: Session, *, session_id: str, event: ToolEvent) -> SessionArtifactRecord:
        payload: dict[str, Any] = {"arguments": event.arguments}
        if event.outcome is not None:
            payload["outcome"] = event.outcome
        if event.error is not None:
            payload["error"] = event.error
        return self.append_artifact(
            db,
            session_id=session_id,
            artifact_kind="tool_result",
            correlation_id=event.correlation_id,
            capability_name=event.capability_name,
            status=event.status,
            payload=payload,
        )

    def append_outbound_intent(
        self,
        db: Session,
        *,
        session_id: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> SessionArtifactRecord:
        return self.append_artifact(
            db,
            session_id=session_id,
            artifact_kind="outbound_intent",
            correlation_id=correlation_id,
            capability_name="send_message",
            status="prepared",
            payload=payload,
        )

    def append_governance_event(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        event_kind: str,
        payload: dict[str, Any],
        proposal_id: str | None = None,
        resource_version_id: str | None = None,
        approval_id: str | None = None,
        active_resource_id: str | None = None,
    ) -> GovernanceTranscriptEventRecord:
        event = GovernanceTranscriptEventRecord(
            session_id=session_id,
            message_id=message_id,
            event_kind=event_kind,
            proposal_id=proposal_id,
            resource_version_id=resource_version_id,
            approval_id=approval_id,
            active_resource_id=active_resource_id,
            event_payload=json.dumps(payload, sort_keys=True),
        )
        db.add(event)
        db.flush()
        return event

    def create_governance_proposal(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        agent_id: str,
        requested_by: str,
        capability_name: str,
        arguments: dict[str, Any],
    ) -> tuple[ResourceProposalRecord, ResourceVersionRecord]:
        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            raise ValueError(f"unknown capability: {capability_name}")

        payload = {
            "capability_name": capability_name,
            "typed_action_id": typed_action.typed_action_id,
            "arguments": arguments,
        }
        payload_json = canonicalize_params(payload)
        content_hash = hash_payload(payload_json)

        existing = self.find_matching_proposal(
            db,
            session_id=session_id,
            agent_id=agent_id,
            capability_name=capability_name,
            arguments=arguments,
            states=("pending_approval",),
        )
        if existing is not None:
            version = db.get(ResourceVersionRecord, existing.latest_version_id)
            if version is None:
                raise RuntimeError("proposal missing latest version")
            return existing, version

        proposal = ResourceProposalRecord(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            resource_kind=typed_action.resource_kind,
            requested_by=requested_by,
            current_state="proposed",
            proposed_at=datetime.now(timezone.utc),
        )
        db.add(proposal)
        db.flush()

        version = ResourceVersionRecord(
            proposal_id=proposal.id,
            version_number=1,
            content_hash=content_hash,
            resource_payload=payload_json,
        )
        db.add(version)
        db.flush()

        proposal.latest_version_id = version.id
        proposal.current_state = "pending_approval"
        proposal.pending_approval_at = datetime.now(timezone.utc)
        db.flush()

        self.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="proposal_created",
            proposal_id=proposal.id,
            resource_version_id=version.id,
            payload={
                "capability_name": capability_name,
                "typed_action_id": typed_action.typed_action_id,
                "content_hash": content_hash,
                "arguments": arguments,
            },
        )
        self.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="approval_requested",
            proposal_id=proposal.id,
            resource_version_id=version.id,
            payload={
                "capability_name": capability_name,
                "typed_action_id": typed_action.typed_action_id,
                "arguments": arguments,
                "current_state": proposal.current_state,
            },
        )
        return proposal, version

    def find_matching_proposal(
        self,
        db: Session,
        *,
        session_id: str,
        agent_id: str,
        capability_name: str,
        arguments: dict[str, Any],
        states: tuple[str, ...],
    ) -> ResourceProposalRecord | None:
        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            return None

        payload_json = canonicalize_params(
            {
                "capability_name": capability_name,
                "typed_action_id": typed_action.typed_action_id,
                "arguments": arguments,
            }
        )
        content_hash = hash_payload(payload_json)
        stmt = (
            select(ResourceProposalRecord)
            .join(ResourceVersionRecord, ResourceProposalRecord.latest_version_id == ResourceVersionRecord.id)
            .where(
                ResourceProposalRecord.session_id == session_id,
                ResourceProposalRecord.agent_id == agent_id,
                ResourceProposalRecord.current_state.in_(states),
                ResourceVersionRecord.content_hash == content_hash,
            )
            .order_by(ResourceProposalRecord.created_at.desc())
        )
        return db.scalar(stmt)

    def approve_proposal(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        proposal_id: str,
        approver_id: str,
    ) -> ResourceApprovalRecord:
        proposal = db.get(ResourceProposalRecord, proposal_id)
        if proposal is None:
            raise LookupError("proposal not found")
        if proposal.current_state not in {"pending_approval", "approved"}:
            raise ValueError("proposal cannot be approved from current state")

        version = db.get(ResourceVersionRecord, proposal.latest_version_id)
        if version is None:
            raise LookupError("proposal version not found")

        payload = json.loads(version.resource_payload)
        typed_action_id = payload["typed_action_id"]
        canonical_params_json = canonicalize_params(payload["arguments"])
        canonical_params_hash = hash_payload(canonical_params_json)
        approved_at = datetime.now(timezone.utc)
        packet_json = canonicalize_params(
            {
                "proposal_id": proposal.id,
                "resource_version_id": version.id,
                "content_hash": version.content_hash,
                "typed_action_id": typed_action_id,
                "canonical_params_json": canonical_params_json,
                "canonical_params_hash": canonical_params_hash,
                "scope_kind": "session_agent",
                "approver_id": approver_id,
                "approved_at": approved_at.isoformat(),
            }
        )
        approval_packet_hash = hash_payload(packet_json)

        approval = db.scalar(
            select(ResourceApprovalRecord).where(
                ResourceApprovalRecord.proposal_id == proposal.id,
                ResourceApprovalRecord.resource_version_id == version.id,
                ResourceApprovalRecord.typed_action_id == typed_action_id,
                ResourceApprovalRecord.canonical_params_hash == canonical_params_hash,
            )
        )
        if approval is None:
            approval = ResourceApprovalRecord(
                proposal_id=proposal.id,
                resource_version_id=version.id,
                approval_packet_hash=approval_packet_hash,
                typed_action_id=typed_action_id,
                canonical_params_json=canonical_params_json,
                canonical_params_hash=canonical_params_hash,
                scope_kind="session_agent",
                approver_id=approver_id,
                approved_at=approved_at,
            )
            db.add(approval)
            db.flush()

        proposal.current_state = "approved"
        proposal.approved_at = approved_at
        db.flush()

        self.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="approval_decision",
            proposal_id=proposal.id,
            resource_version_id=version.id,
            approval_id=approval.id,
            payload={
                "decision": "approved",
                "approver_id": approver_id,
                "typed_action_id": typed_action_id,
                "canonical_params_hash": canonical_params_hash,
            },
        )
        return approval

    def deny_proposal(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        proposal_id: str,
        approver_id: str,
    ) -> ResourceProposalRecord:
        proposal = db.get(ResourceProposalRecord, proposal_id)
        if proposal is None:
            raise LookupError("proposal not found")
        proposal.current_state = "denied"
        proposal.denied_at = datetime.now(timezone.utc)
        db.flush()
        self.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="approval_decision",
            proposal_id=proposal.id,
            resource_version_id=proposal.latest_version_id,
            payload={"decision": "denied", "approver_id": approver_id},
        )
        return proposal

    def activate_approved_resource(
        self,
        db: Session,
        *,
        proposal_id: str,
        resource_version_id: str,
        typed_action_id: str,
        canonical_params_hash: str,
    ) -> tuple[ActiveResourceRecord, bool]:
        existing = db.scalar(
            select(ActiveResourceRecord).where(
                ActiveResourceRecord.proposal_id == proposal_id,
                ActiveResourceRecord.resource_version_id == resource_version_id,
                ActiveResourceRecord.typed_action_id == typed_action_id,
                ActiveResourceRecord.canonical_params_hash == canonical_params_hash,
            )
        )
        if existing is not None:
            if existing.activation_state != "active":
                existing.activation_state = "active"
                existing.activated_at = datetime.now(timezone.utc)
                db.flush()
            return existing, False

        active = ActiveResourceRecord(
            proposal_id=proposal_id,
            resource_version_id=resource_version_id,
            typed_action_id=typed_action_id,
            canonical_params_hash=canonical_params_hash,
            activation_state="active",
            activated_at=datetime.now(timezone.utc),
        )
        db.add(active)
        db.flush()
        return active, True

    def revoke_proposal(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        proposal_id: str,
        revoked_by: str,
        reason: str,
    ) -> bool:
        proposal = db.get(ResourceProposalRecord, proposal_id)
        if proposal is None:
            return False
        version_id = proposal.latest_version_id
        approvals = list(
            db.scalars(
                select(ResourceApprovalRecord).where(
                    ResourceApprovalRecord.proposal_id == proposal_id,
                    ResourceApprovalRecord.revoked_at.is_(None),
                )
            )
        )
        now = datetime.now(timezone.utc)
        for approval in approvals:
            approval.revoked_at = now
            approval.revoked_by = revoked_by

        active_resources = list(
            db.scalars(
                select(ActiveResourceRecord).where(
                    ActiveResourceRecord.proposal_id == proposal_id,
                    ActiveResourceRecord.activation_state == "active",
                )
            )
        )
        for active in active_resources:
            active.activation_state = "revoked"
            active.revoked_at = now
            active.revocation_reason = reason

        db.flush()
        self.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="revocation_result",
            proposal_id=proposal_id,
            resource_version_id=version_id,
            payload={
                "revoked_by": revoked_by,
                "reason": reason,
                "revoked_approvals": len(approvals),
                "revoked_active_resources": len(active_resources),
            },
        )
        return True

    def list_active_approvals(
        self,
        db: Session,
        *,
        session_id: str,
        agent_id: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ResourceApprovalRecord, ResourceProposalRecord, ResourceVersionRecord, ActiveResourceRecord)
            .join(ResourceProposalRecord, ResourceApprovalRecord.proposal_id == ResourceProposalRecord.id)
            .join(ResourceVersionRecord, ResourceApprovalRecord.resource_version_id == ResourceVersionRecord.id)
            .join(
                ActiveResourceRecord,
                and_(
                    ActiveResourceRecord.proposal_id == ResourceApprovalRecord.proposal_id,
                    ActiveResourceRecord.resource_version_id == ResourceApprovalRecord.resource_version_id,
                    ActiveResourceRecord.typed_action_id == ResourceApprovalRecord.typed_action_id,
                    ActiveResourceRecord.canonical_params_hash == ResourceApprovalRecord.canonical_params_hash,
                ),
            )
            .where(
                ResourceProposalRecord.session_id == session_id,
                ResourceProposalRecord.agent_id == agent_id,
                ResourceProposalRecord.current_state == "approved",
                ResourceApprovalRecord.revoked_at.is_(None),
                or_(ResourceApprovalRecord.expires_at.is_(None), ResourceApprovalRecord.expires_at > now),
                ActiveResourceRecord.activation_state == "active",
            )
        )
        approvals: list[dict[str, Any]] = []
        for approval, proposal, version, active in db.execute(stmt).all():
            payload = json.loads(version.resource_payload)
            approvals.append(
                {
                    "approval_id": approval.id,
                    "proposal_id": proposal.id,
                    "resource_version_id": version.id,
                    "content_hash": version.content_hash,
                    "typed_action_id": approval.typed_action_id,
                    "canonical_params_json": approval.canonical_params_json,
                    "canonical_params_hash": approval.canonical_params_hash,
                    "active_resource_id": active.id,
                    "capability_name": payload["capability_name"],
                }
            )
        return approvals

    def get_pending_proposal(self, db: Session, *, proposal_id: str) -> ResourceProposalRecord | None:
        proposal = db.get(ResourceProposalRecord, proposal_id)
        if proposal is None or proposal.current_state != "pending_approval":
            return None
        return proposal

    def get_proposal_packet(self, db: Session, *, proposal_id: str) -> dict[str, Any] | None:
        proposal = db.get(ResourceProposalRecord, proposal_id)
        if proposal is None or proposal.latest_version_id is None:
            return None
        version = db.get(ResourceVersionRecord, proposal.latest_version_id)
        if version is None:
            return None
        payload = json.loads(version.resource_payload)
        canonical_params_json = canonicalize_params(payload["arguments"])
        return {
            "proposal_id": proposal.id,
            "resource_version_id": version.id,
            "content_hash": version.content_hash,
            "typed_action_id": payload["typed_action_id"],
            "capability_name": payload["capability_name"],
            "canonical_params_json": canonical_params_json,
            "canonical_params_hash": hash_payload(canonical_params_json),
            "scope_kind": "session_agent",
        }

    def list_pending_approvals(self, db: Session, *, session_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ResourceProposalRecord, ResourceVersionRecord)
            .join(ResourceVersionRecord, ResourceProposalRecord.latest_version_id == ResourceVersionRecord.id)
            .where(
                ResourceProposalRecord.session_id == session_id,
                ResourceProposalRecord.current_state == "pending_approval",
            )
            .order_by(ResourceProposalRecord.pending_approval_at.asc(), ResourceProposalRecord.created_at.asc())
        )
        items: list[dict[str, Any]] = []
        for proposal, version in db.execute(stmt).all():
            payload = json.loads(version.resource_payload)
            canonical_params = payload["arguments"]
            canonical_params_json = canonicalize_params(canonical_params)
            items.append(
                {
                    "proposal_id": proposal.id,
                    "message_id": proposal.message_id,
                    "agent_id": proposal.agent_id,
                    "requested_by": proposal.requested_by,
                    "current_state": proposal.current_state,
                    "resource_kind": proposal.resource_kind,
                    "resource_version_id": version.id,
                    "capability_name": payload["capability_name"],
                    "typed_action_id": payload["typed_action_id"],
                    "content_hash": version.content_hash,
                    "canonical_params": canonical_params,
                    "canonical_params_json": canonical_params_json,
                    "scope_kind": "session_agent",
                    "next_action": f"approve {proposal.id}",
                    "proposed_at": proposal.proposed_at,
                    "pending_approval_at": proposal.pending_approval_at,
                }
            )
        return items

    def list_conversation_messages(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        rows = self.list_messages(db, session_id=session_id, limit=limit, before_message_id=None)
        return [
            ConversationMessage(role=row.role, content=row.content, sender_id=row.sender_id)
            for row in rows
        ]

    def list_messages(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int,
        before_message_id: int | None,
    ) -> list[MessageRecord]:
        stmt = select(MessageRecord).where(MessageRecord.session_id == session_id)
        if before_message_id is not None:
            stmt = stmt.where(MessageRecord.id < before_message_id)
        rows = list(db.scalars(stmt.order_by(MessageRecord.id.desc()).limit(limit)))
        rows.reverse()
        return rows

    def list_artifacts(self, db: Session, *, session_id: str) -> list[SessionArtifactRecord]:
        stmt = (
            select(SessionArtifactRecord)
            .where(SessionArtifactRecord.session_id == session_id)
            .order_by(SessionArtifactRecord.id.asc())
        )
        return list(db.scalars(stmt))
