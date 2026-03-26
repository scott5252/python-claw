from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import (
    ActiveResourceRecord,
    AttachmentExtractionRecord,
    ContextManifestRecord,
    GovernanceTranscriptEventRecord,
    InboundMessageAttachmentRecord,
    MessageRecord,
    MessageAttachmentRecord,
    OutboundDeliveryAttemptRecord,
    OutboundDeliveryRecord,
    OutboxJobRecord,
    RetrievalRecord,
    ResourceApprovalRecord,
    ResourceProposalRecord,
    ResourceVersionRecord,
    ScheduledJobRecord,
    SessionMemoryRecord,
    SessionArtifactRecord,
    SessionRecord,
    SummarySnapshotRecord,
)
from src.graphs.state import ConversationMessage, ToolEvent, ToolRequest
from src.policies.service import build_approval_identity_hash, canonicalize_params, default_tool_schema_identity, hash_payload
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

    def get_session_channel_kind(self, db: Session, *, session_id: str) -> str:
        session = self.get_session(db, session_id)
        if session is None:
            raise RuntimeError("session not found")
        return session.channel_kind

    def get_message(self, db: Session, *, message_id: int | None) -> MessageRecord | None:
        if message_id is None:
            return None
        return db.get(MessageRecord, message_id)

    def get_scheduled_job_by_key(self, db: Session, *, job_key: str) -> ScheduledJobRecord | None:
        return db.scalar(select(ScheduledJobRecord).where(ScheduledJobRecord.job_key == job_key))

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

    def append_inbound_attachments(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        attachments: list[dict[str, Any]],
    ) -> list[InboundMessageAttachmentRecord]:
        rows: list[InboundMessageAttachmentRecord] = []
        for ordinal, attachment in enumerate(attachments):
            row = InboundMessageAttachmentRecord(
                session_id=session_id,
                message_id=message_id,
                ordinal=ordinal,
                external_attachment_id=attachment.get("external_attachment_id"),
                source_url=attachment["source_url"],
                mime_type=attachment["mime_type"],
                filename=attachment.get("filename"),
                byte_size=attachment.get("byte_size"),
                provider_metadata_json=json.dumps(attachment.get("provider_metadata", {}), sort_keys=True),
            )
            db.add(row)
            rows.append(row)
        db.flush()
        return rows

    def list_inbound_attachments(self, db: Session, *, message_id: int) -> list[InboundMessageAttachmentRecord]:
        stmt = (
            select(InboundMessageAttachmentRecord)
            .where(InboundMessageAttachmentRecord.message_id == message_id)
            .order_by(InboundMessageAttachmentRecord.ordinal.asc(), InboundMessageAttachmentRecord.id.asc())
        )
        return list(db.scalars(stmt))

    def list_message_attachments_for_message(self, db: Session, *, message_id: int) -> list[MessageAttachmentRecord]:
        stmt = (
            select(MessageAttachmentRecord)
            .where(MessageAttachmentRecord.message_id == message_id)
            .order_by(MessageAttachmentRecord.ordinal.asc(), MessageAttachmentRecord.id.asc())
        )
        return list(db.scalars(stmt))

    def get_message_attachment(self, db: Session, *, attachment_id: int) -> MessageAttachmentRecord | None:
        return db.get(MessageAttachmentRecord, attachment_id)

    def list_stored_message_attachments_for_message(
        self,
        db: Session,
        *,
        message_id: int,
    ) -> list[MessageAttachmentRecord]:
        inbound_rows = self.list_inbound_attachments(db, message_id=message_id)
        stored: list[MessageAttachmentRecord] = []
        for inbound in inbound_rows:
            latest = self.get_latest_message_attachment_for_inbound(
                db,
                inbound_message_attachment_id=inbound.id,
            )
            if latest is not None and latest.normalization_status == "stored":
                stored.append(latest)
        stored.sort(key=lambda item: (item.ordinal, item.id))
        return stored

    def get_latest_message_attachment_for_inbound(
        self,
        db: Session,
        *,
        inbound_message_attachment_id: int,
    ) -> MessageAttachmentRecord | None:
        stmt = (
            select(MessageAttachmentRecord)
            .where(MessageAttachmentRecord.inbound_message_attachment_id == inbound_message_attachment_id)
            .order_by(MessageAttachmentRecord.created_at.desc(), MessageAttachmentRecord.id.desc())
        )
        return db.scalar(stmt)

    def get_summary_snapshot(self, db: Session, *, summary_snapshot_id: int) -> SummarySnapshotRecord | None:
        return db.get(SummarySnapshotRecord, summary_snapshot_id)

    def append_message_attachment(
        self,
        db: Session,
        *,
        inbound_attachment_id: int,
        message_id: int,
        session_id: str,
        ordinal: int,
        external_attachment_id: str | None,
        source_url: str,
        storage_key: str | None,
        storage_bucket: str | None,
        mime_type: str,
        media_kind: str,
        filename: str | None,
        byte_size: int | None,
        sha256: str | None,
        normalization_status: str,
        retention_expires_at: datetime | None,
        provider_metadata: dict[str, Any],
        error_detail: str | None = None,
    ) -> MessageAttachmentRecord:
        record = MessageAttachmentRecord(
            inbound_message_attachment_id=inbound_attachment_id,
            message_id=message_id,
            session_id=session_id,
            ordinal=ordinal,
            external_attachment_id=external_attachment_id,
            source_url=source_url,
            storage_key=storage_key,
            storage_bucket=storage_bucket,
            mime_type=mime_type,
            media_kind=media_kind,
            filename=filename,
            byte_size=byte_size,
            sha256=sha256,
            normalization_status=normalization_status,
            retention_expires_at=retention_expires_at,
            provider_metadata_json=json.dumps(provider_metadata, sort_keys=True),
            error_detail=error_detail,
        )
        db.add(record)
        db.flush()
        return record

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
        payload: dict[str, Any] = {"arguments": request.arguments}
        if request.metadata:
            payload["metadata"] = request.metadata
        return self.append_artifact(
            db,
            session_id=session_id,
            artifact_kind="tool_proposal",
            correlation_id=request.correlation_id,
            capability_name=request.capability_name,
            status="requested",
            payload=payload,
        )

    def append_tool_event(self, db: Session, *, session_id: str, event: ToolEvent) -> SessionArtifactRecord:
        payload: dict[str, Any] = {"arguments": event.arguments}
        if event.outcome is not None:
            payload["outcome"] = event.outcome
        if event.error is not None:
            payload["error"] = event.error
        if event.metadata:
            payload["metadata"] = event.metadata
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

    def list_outbound_intents_for_run(
        self,
        db: Session,
        *,
        session_id: str,
        execution_run_id: str,
    ) -> list[SessionArtifactRecord]:
        artifacts = self.list_artifacts(db, session_id=session_id)
        results: list[SessionArtifactRecord] = []
        for artifact in artifacts:
            if artifact.artifact_kind != "outbound_intent":
                continue
            payload = json.loads(artifact.payload_json)
            if payload.get("execution_run_id") == execution_run_id:
                results.append(artifact)
        return results

    def get_message_attachment(self, db: Session, *, attachment_id: int) -> MessageAttachmentRecord | None:
        return db.get(MessageAttachmentRecord, attachment_id)

    def create_or_get_outbound_delivery(
        self,
        db: Session,
        *,
        session_id: str,
        execution_run_id: str,
        trace_id: str | None,
        outbound_intent_id: int,
        channel_kind: str,
        channel_account_id: str,
        delivery_kind: str,
        chunk_index: int,
        chunk_count: int,
        reply_to_external_id: str | None,
        attachment_id: int | None,
    ) -> OutboundDeliveryRecord:
        existing = db.scalar(
            select(OutboundDeliveryRecord).where(
                OutboundDeliveryRecord.outbound_intent_id == outbound_intent_id,
                OutboundDeliveryRecord.chunk_index == chunk_index,
            )
        )
        if existing is not None:
            return existing
        record = OutboundDeliveryRecord(
            session_id=session_id,
            execution_run_id=execution_run_id,
            outbound_intent_id=outbound_intent_id,
            channel_kind=channel_kind,
            channel_account_id=channel_account_id,
            delivery_kind=delivery_kind,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            reply_to_external_id=reply_to_external_id,
            attachment_id=attachment_id,
            status="pending",
            trace_id=trace_id,
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(
                select(OutboundDeliveryRecord).where(
                    OutboundDeliveryRecord.outbound_intent_id == outbound_intent_id,
                    OutboundDeliveryRecord.chunk_index == chunk_index,
                )
            )
            if existing is None:
                raise
            return existing
        return record

    def create_outbound_delivery_attempt(
        self,
        db: Session,
        *,
        outbound_delivery_id: int,
        trace_id: str | None,
        provider_idempotency_key: str | None,
    ) -> OutboundDeliveryAttemptRecord:
        last_attempt = db.scalar(
            select(OutboundDeliveryAttemptRecord)
            .where(OutboundDeliveryAttemptRecord.outbound_delivery_id == outbound_delivery_id)
            .order_by(
                OutboundDeliveryAttemptRecord.attempt_number.desc(),
                OutboundDeliveryAttemptRecord.id.desc(),
            )
        )
        attempt = OutboundDeliveryAttemptRecord(
            outbound_delivery_id=outbound_delivery_id,
            attempt_number=1 if last_attempt is None else last_attempt.attempt_number + 1,
            provider_idempotency_key=provider_idempotency_key,
            status="started",
            trace_id=trace_id,
        )
        db.add(attempt)
        db.flush()
        return attempt

    def mark_outbound_delivery_sent(
        self,
        db: Session,
        *,
        delivery_id: int,
        attempt_id: int,
        provider_message_id: str,
    ) -> None:
        delivery = db.get(OutboundDeliveryRecord, delivery_id)
        attempt = db.get(OutboundDeliveryAttemptRecord, attempt_id)
        if delivery is None or attempt is None:
            raise RuntimeError("outbound delivery state missing")
        delivery.status = "sent"
        delivery.provider_message_id = provider_message_id
        delivery.error_code = None
        delivery.error_detail = None
        delivery.failure_category = None
        attempt.status = "sent"
        attempt.provider_message_id = provider_message_id
        attempt.error_code = None
        attempt.error_detail = None
        db.flush()

    def mark_outbound_delivery_failed(
        self,
        db: Session,
        *,
        delivery_id: int,
        attempt_id: int,
        error_code: str,
        error_detail: str,
    ) -> None:
        delivery = db.get(OutboundDeliveryRecord, delivery_id)
        attempt = db.get(OutboundDeliveryAttemptRecord, attempt_id)
        if delivery is None or attempt is None:
            raise RuntimeError("outbound delivery state missing")
        delivery.status = "failed"
        delivery.error_code = error_code
        delivery.error_detail = error_detail
        delivery.failure_category = "delivery_failed"
        attempt.status = "failed"
        attempt.error_code = error_code
        attempt.error_detail = error_detail
        db.flush()

    def list_outbound_deliveries(self, db: Session, *, session_id: str) -> list[OutboundDeliveryRecord]:
        stmt = (
            select(OutboundDeliveryRecord)
            .where(OutboundDeliveryRecord.session_id == session_id)
            .order_by(OutboundDeliveryRecord.created_at.asc(), OutboundDeliveryRecord.id.asc())
        )
        return list(db.scalars(stmt))

    def list_outbound_delivery_attempts(
        self,
        db: Session,
        *,
        delivery_id: int,
    ) -> list[OutboundDeliveryAttemptRecord]:
        stmt = (
            select(OutboundDeliveryAttemptRecord)
            .where(OutboundDeliveryAttemptRecord.outbound_delivery_id == delivery_id)
            .order_by(OutboundDeliveryAttemptRecord.attempt_number.asc(), OutboundDeliveryAttemptRecord.id.asc())
        )
        return list(db.scalars(stmt))

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
        tool_schema_name: str | None = None,
        tool_schema_version: str | None = None,
    ) -> tuple[ResourceProposalRecord, ResourceVersionRecord]:
        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            raise ValueError(f"unknown capability: {capability_name}")
        resolved_schema_name, resolved_schema_version = default_tool_schema_identity(capability_name)
        if tool_schema_name is None:
            tool_schema_name = resolved_schema_name
        if tool_schema_version is None:
            tool_schema_version = resolved_schema_version

        payload = {
            "capability_name": capability_name,
            "typed_action_id": typed_action.typed_action_id,
            "tool_schema_name": tool_schema_name,
            "tool_schema_version": tool_schema_version,
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
            tool_schema_name=tool_schema_name,
            tool_schema_version=tool_schema_version,
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
                "tool_schema_name": tool_schema_name,
                "tool_schema_version": tool_schema_version,
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
                "tool_schema_name": tool_schema_name,
                "tool_schema_version": tool_schema_version,
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
        tool_schema_name: str | None,
        tool_schema_version: str | None,
        states: tuple[str, ...],
    ) -> ResourceProposalRecord | None:
        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            return None
        resolved_schema_name, resolved_schema_version = default_tool_schema_identity(capability_name)
        if tool_schema_name is None:
            tool_schema_name = resolved_schema_name
        if tool_schema_version is None:
            tool_schema_version = resolved_schema_version

        payload_json = canonicalize_params(
            {
                "capability_name": capability_name,
                "typed_action_id": typed_action.typed_action_id,
                "tool_schema_name": tool_schema_name,
                "tool_schema_version": tool_schema_version,
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
        tool_schema_name = payload["tool_schema_name"]
        tool_schema_version = payload["tool_schema_version"]
        canonical_params_json = canonicalize_params(payload["arguments"])
        canonical_params_hash = build_approval_identity_hash(
            tool_schema_name=tool_schema_name,
            tool_schema_version=tool_schema_version,
            canonical_arguments_json=canonical_params_json,
        )
        approved_at = datetime.now(timezone.utc)
        packet_json = canonicalize_params(
            {
                "proposal_id": proposal.id,
                "resource_version_id": version.id,
                "content_hash": version.content_hash,
                "typed_action_id": typed_action_id,
                "tool_schema_name": tool_schema_name,
                "tool_schema_version": tool_schema_version,
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
                "tool_schema_name": tool_schema_name,
                "tool_schema_version": tool_schema_version,
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
                    "tool_schema_name": payload["tool_schema_name"],
                    "tool_schema_version": payload["tool_schema_version"],
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
            "tool_schema_name": payload["tool_schema_name"],
            "tool_schema_version": payload["tool_schema_version"],
            "canonical_params_json": canonical_params_json,
            "canonical_params_hash": build_approval_identity_hash(
                tool_schema_name=payload["tool_schema_name"],
                tool_schema_version=payload["tool_schema_version"],
                canonical_arguments_json=canonical_params_json,
            ),
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
                    "tool_schema_name": payload["tool_schema_name"],
                    "tool_schema_version": payload["tool_schema_version"],
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

    def list_governance_events(self, db: Session, *, session_id: str) -> list[GovernanceTranscriptEventRecord]:
        stmt = (
            select(GovernanceTranscriptEventRecord)
            .where(GovernanceTranscriptEventRecord.session_id == session_id)
            .order_by(GovernanceTranscriptEventRecord.created_at.asc(), GovernanceTranscriptEventRecord.id.asc())
        )
        return list(db.scalars(stmt))

    def append_summary_snapshot(
        self,
        db: Session,
        *,
        session_id: str,
        base_message_id: int,
        through_message_id: int,
        source_watermark_message_id: int,
        summary_text: str,
        summary_metadata: dict[str, Any] | None = None,
    ) -> SummarySnapshotRecord:
        latest = db.scalar(
            select(SummarySnapshotRecord)
            .where(SummarySnapshotRecord.session_id == session_id)
            .order_by(SummarySnapshotRecord.snapshot_version.desc())
        )
        snapshot = SummarySnapshotRecord(
            session_id=session_id,
            snapshot_version=1 if latest is None else latest.snapshot_version + 1,
            base_message_id=base_message_id,
            through_message_id=through_message_id,
            source_watermark_message_id=source_watermark_message_id,
            summary_text=summary_text,
            summary_metadata_json=None if summary_metadata is None else json.dumps(summary_metadata, sort_keys=True),
        )
        db.add(snapshot)
        db.flush()
        return snapshot

    def get_latest_valid_summary_snapshot(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
    ) -> SummarySnapshotRecord | None:
        stmt = (
            select(SummarySnapshotRecord)
            .where(
                SummarySnapshotRecord.session_id == session_id,
                SummarySnapshotRecord.through_message_id < message_id,
                SummarySnapshotRecord.source_watermark_message_id <= message_id,
            )
            .order_by(
                SummarySnapshotRecord.through_message_id.desc(),
                SummarySnapshotRecord.snapshot_version.desc(),
            )
        )
        return db.scalar(stmt)

    def get_latest_summary_snapshot_for_session(self, db: Session, *, session_id: str) -> SummarySnapshotRecord | None:
        stmt = (
            select(SummarySnapshotRecord)
            .where(SummarySnapshotRecord.session_id == session_id)
            .order_by(SummarySnapshotRecord.snapshot_version.desc())
        )
        return db.scalar(stmt)

    def create_or_get_session_memory(
        self,
        db: Session,
        *,
        session_id: str,
        memory_kind: str,
        content_text: str,
        content_hash: str,
        status: str,
        confidence: float | None,
        source_kind: str,
        source_message_id: int | None,
        source_summary_snapshot_id: int | None,
        source_base_message_id: int | None,
        source_through_message_id: int | None,
        derivation_strategy_id: str,
        payload: dict[str, Any] | None = None,
    ) -> SessionMemoryRecord:
        self._validate_memory_provenance(
            source_kind=source_kind,
            source_message_id=source_message_id,
            source_summary_snapshot_id=source_summary_snapshot_id,
            source_base_message_id=source_base_message_id,
            source_through_message_id=source_through_message_id,
        )
        existing_stmt = select(SessionMemoryRecord).where(
            SessionMemoryRecord.session_id == session_id,
            SessionMemoryRecord.memory_kind == memory_kind,
            SessionMemoryRecord.content_hash == content_hash,
            SessionMemoryRecord.derivation_strategy_id == derivation_strategy_id,
            SessionMemoryRecord.source_kind == source_kind,
        )
        if source_kind == "message":
            existing_stmt = existing_stmt.where(SessionMemoryRecord.source_message_id == source_message_id)
        else:
            existing_stmt = existing_stmt.where(SessionMemoryRecord.source_summary_snapshot_id == source_summary_snapshot_id)
        existing = db.scalar(existing_stmt.order_by(SessionMemoryRecord.id.desc()))
        if existing is not None:
            return existing
        record = SessionMemoryRecord(
            session_id=session_id,
            memory_kind=memory_kind,
            content_text=content_text,
            content_hash=content_hash,
            status=status,
            confidence=confidence,
            source_kind=source_kind,
            source_message_id=source_message_id,
            source_summary_snapshot_id=source_summary_snapshot_id,
            source_base_message_id=source_base_message_id,
            source_through_message_id=source_through_message_id,
            derivation_strategy_id=derivation_strategy_id,
            payload_json=json.dumps(payload or {}, sort_keys=True),
        )
        db.add(record)
        db.flush()
        return record

    def get_session_memory(self, db: Session, *, memory_id: int) -> SessionMemoryRecord | None:
        return db.get(SessionMemoryRecord, memory_id)

    def list_active_session_memories(self, db: Session, *, session_id: str) -> list[SessionMemoryRecord]:
        stmt = (
            select(SessionMemoryRecord)
            .where(SessionMemoryRecord.session_id == session_id, SessionMemoryRecord.status == "active")
            .order_by(SessionMemoryRecord.created_at.desc(), SessionMemoryRecord.id.desc())
        )
        return list(db.scalars(stmt))

    def transition_session_memory(self, db: Session, *, memory_id: int, status: str) -> SessionMemoryRecord:
        record = db.get(SessionMemoryRecord, memory_id)
        if record is None:
            raise LookupError("session memory not found")
        record.status = status
        db.flush()
        return record

    def create_or_get_retrieval_record(
        self,
        db: Session,
        *,
        session_id: str,
        source_kind: str,
        source_id: int,
        source_message_id: int | None,
        source_summary_snapshot_id: int | None,
        source_memory_id: int | None,
        source_attachment_extraction_id: int | None,
        chunk_index: int,
        content_text: str,
        content_hash: str,
        ranking_metadata: dict[str, Any] | None,
        derivation_strategy_id: str,
    ) -> RetrievalRecord:
        existing = db.scalar(
            select(RetrievalRecord).where(
                RetrievalRecord.session_id == session_id,
                RetrievalRecord.source_kind == source_kind,
                RetrievalRecord.source_id == source_id,
                RetrievalRecord.chunk_index == chunk_index,
                RetrievalRecord.content_hash == content_hash,
                RetrievalRecord.derivation_strategy_id == derivation_strategy_id,
            )
        )
        if existing is not None:
            return existing
        record = RetrievalRecord(
            session_id=session_id,
            source_kind=source_kind,
            source_id=source_id,
            source_message_id=source_message_id,
            source_summary_snapshot_id=source_summary_snapshot_id,
            source_memory_id=source_memory_id,
            source_attachment_extraction_id=source_attachment_extraction_id,
            chunk_index=chunk_index,
            content_text=content_text,
            content_hash=content_hash,
            ranking_metadata_json=json.dumps(ranking_metadata or {}, sort_keys=True),
            derivation_strategy_id=derivation_strategy_id,
        )
        db.add(record)
        db.flush()
        return record

    def list_retrieval_records(self, db: Session, *, session_id: str) -> list[RetrievalRecord]:
        stmt = (
            select(RetrievalRecord)
            .where(RetrievalRecord.session_id == session_id)
            .order_by(RetrievalRecord.created_at.desc(), RetrievalRecord.id.desc())
        )
        return list(db.scalars(stmt))

    def get_attachment_extraction(
        self,
        db: Session,
        *,
        attachment_id: int,
        extractor_kind: str,
        derivation_strategy_id: str,
    ) -> AttachmentExtractionRecord | None:
        stmt = select(AttachmentExtractionRecord).where(
            AttachmentExtractionRecord.attachment_id == attachment_id,
            AttachmentExtractionRecord.extractor_kind == extractor_kind,
            AttachmentExtractionRecord.derivation_strategy_id == derivation_strategy_id,
        )
        return db.scalar(stmt)

    def get_attachment_extraction_by_id(
        self,
        db: Session,
        *,
        attachment_extraction_id: int,
    ) -> AttachmentExtractionRecord | None:
        return db.get(AttachmentExtractionRecord, attachment_extraction_id)

    def upsert_attachment_extraction(
        self,
        db: Session,
        *,
        session_id: str,
        attachment_id: int,
        extractor_kind: str,
        derivation_strategy_id: str,
        status: str,
        content_text: str | None = None,
        content_metadata: dict[str, Any] | None = None,
        error_detail: str | None = None,
    ) -> AttachmentExtractionRecord:
        record = self.get_attachment_extraction(
            db,
            attachment_id=attachment_id,
            extractor_kind=extractor_kind,
            derivation_strategy_id=derivation_strategy_id,
        )
        if record is None:
            record = AttachmentExtractionRecord(
                session_id=session_id,
                attachment_id=attachment_id,
                extractor_kind=extractor_kind,
                derivation_strategy_id=derivation_strategy_id,
                status=status,
                content_text=content_text,
                content_metadata_json=json.dumps(content_metadata or {}, sort_keys=True),
                error_detail=error_detail,
            )
            db.add(record)
        else:
            record.status = status
            record.content_text = content_text
            record.content_metadata_json = json.dumps(content_metadata or {}, sort_keys=True)
            record.error_detail = error_detail
        db.flush()
        return record

    def list_attachment_extractions_for_attachments(
        self,
        db: Session,
        *,
        attachment_ids: list[int],
    ) -> list[AttachmentExtractionRecord]:
        if not attachment_ids:
            return []
        stmt = (
            select(AttachmentExtractionRecord)
            .where(AttachmentExtractionRecord.attachment_id.in_(attachment_ids))
            .order_by(AttachmentExtractionRecord.created_at.desc(), AttachmentExtractionRecord.id.desc())
        )
        return list(db.scalars(stmt))

    def append_context_manifest(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        manifest: dict[str, Any],
        degraded: bool,
        retention_limit: int = 25,
    ) -> ContextManifestRecord:
        record = ContextManifestRecord(
            session_id=session_id,
            message_id=message_id,
            manifest_json=json.dumps(manifest, sort_keys=True),
            degraded=degraded,
        )
        db.add(record)
        db.flush()

        retained_ids = list(
            db.scalars(
                select(ContextManifestRecord.id)
                .where(ContextManifestRecord.session_id == session_id)
                .order_by(ContextManifestRecord.created_at.desc(), ContextManifestRecord.id.desc())
                .limit(retention_limit)
            )
        )
        if retained_ids:
            db.execute(
                delete(ContextManifestRecord).where(
                    ContextManifestRecord.session_id == session_id,
                    ContextManifestRecord.id.not_in(retained_ids),
                )
            )
        db.flush()
        return record

    def list_context_manifests(self, db: Session, *, session_id: str) -> list[ContextManifestRecord]:
        stmt = (
            select(ContextManifestRecord)
            .where(ContextManifestRecord.session_id == session_id)
            .order_by(ContextManifestRecord.created_at.asc(), ContextManifestRecord.id.asc())
        )
        return list(db.scalars(stmt))

    def enqueue_outbox_job(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        job_kind: str,
        job_dedupe_key: str,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
        available_at: datetime | None = None,
    ) -> OutboxJobRecord:
        existing = db.scalar(select(OutboxJobRecord).where(OutboxJobRecord.job_dedupe_key == job_dedupe_key))
        if existing is not None:
            return existing
        record = OutboxJobRecord(
            session_id=session_id,
            message_id=message_id,
            job_kind=job_kind,
            job_dedupe_key=job_dedupe_key,
            status="pending",
            available_at=available_at or datetime.now(timezone.utc),
            payload_json=json.dumps(payload or {}, sort_keys=True),
            attempt_count=0,
            trace_id=trace_id,
        )
        db.add(record)
        db.flush()
        return record

    def claim_outbox_jobs(
        self,
        db: Session,
        *,
        session_id: str | None,
        now: datetime,
        limit: int,
    ) -> list[OutboxJobRecord]:
        stmt = select(OutboxJobRecord).where(
            OutboxJobRecord.status == "pending",
            OutboxJobRecord.available_at <= now,
        )
        if session_id is not None:
            stmt = stmt.where(OutboxJobRecord.session_id == session_id)
        jobs = list(
            db.scalars(
                stmt.order_by(OutboxJobRecord.available_at.asc(), OutboxJobRecord.id.asc()).limit(limit)
            )
        )
        for job in jobs:
            job.status = "running"
            job.attempt_count += 1
            job.last_error = None
        db.flush()
        return jobs

    def complete_outbox_job(self, db: Session, *, job_id: int) -> OutboxJobRecord:
        job = db.get(OutboxJobRecord, job_id)
        if job is None:
            raise LookupError("outbox job not found")
        job.status = "completed"
        job.last_error = None
        job.failure_category = None
        db.flush()
        return job

    @staticmethod
    def decode_outbox_payload(job: OutboxJobRecord) -> dict[str, Any]:
        return json.loads(job.payload_json or "{}")

    @staticmethod
    def _validate_memory_provenance(
        *,
        source_kind: str,
        source_message_id: int | None,
        source_summary_snapshot_id: int | None,
        source_base_message_id: int | None,
        source_through_message_id: int | None,
    ) -> None:
        if source_kind == "message":
            if source_message_id is None or source_summary_snapshot_id is not None:
                raise ValueError("message memory provenance requires source_message_id only")
            return
        if source_kind == "summary_snapshot":
            if source_summary_snapshot_id is None or source_message_id is not None:
                raise ValueError("summary memory provenance requires source_summary_snapshot_id only")
            if source_base_message_id is None or source_through_message_id is None:
                raise ValueError("summary memory provenance requires transcript range")
            return
        raise ValueError("unsupported memory source_kind")

    def fail_outbox_job(
        self,
        db: Session,
        *,
        job_id: int,
        error: str,
        available_at: datetime | None = None,
    ) -> OutboxJobRecord:
        job = db.get(OutboxJobRecord, job_id)
        if job is None:
            raise LookupError("outbox job not found")
        job.status = "failed"
        job.last_error = error
        job.failure_category = "unexpected_internal"
        if available_at is not None:
            job.available_at = available_at
        db.flush()
        return job

    def replay_active_approvals(
        self,
        db: Session,
        *,
        session_id: str,
        agent_id: str,
        now: datetime,
    ) -> list[dict[str, Any]]:
        proposals_by_id = {
            proposal.id: proposal
            for proposal in db.scalars(
                select(ResourceProposalRecord).where(
                    ResourceProposalRecord.session_id == session_id,
                    ResourceProposalRecord.agent_id == agent_id,
                )
            )
        }
        versions_by_id = {
            version.id: version
            for version in db.scalars(
                select(ResourceVersionRecord).where(
                    ResourceVersionRecord.proposal_id.in_(proposals_by_id.keys() or [""])
                )
            )
        }
        active: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for event in self.list_governance_events(db, session_id=session_id):
            payload = json.loads(event.event_payload)
            proposal = proposals_by_id.get(event.proposal_id or "")
            version = versions_by_id.get(event.resource_version_id or "")
            if proposal is None or version is None:
                continue
            version_payload = json.loads(version.resource_payload)
            typed_action_id = payload.get("typed_action_id") or version_payload.get("typed_action_id")
            canonical_params_json = canonicalize_params(version_payload["arguments"])
            tool_schema_name = payload.get("tool_schema_name") or version_payload["tool_schema_name"]
            tool_schema_version = payload.get("tool_schema_version") or version_payload["tool_schema_version"]
            canonical_params_hash = payload.get("canonical_params_hash") or build_approval_identity_hash(
                tool_schema_name=tool_schema_name,
                tool_schema_version=tool_schema_version,
                canonical_arguments_json=canonical_params_json,
            )
            key = (proposal.id, version.id, typed_action_id, canonical_params_hash)
            if event.event_kind == "approval_decision" and payload.get("decision") == "approved":
                active[key] = {
                    "approval_id": event.approval_id or f"replay-{proposal.id}",
                    "proposal_id": proposal.id,
                    "resource_version_id": version.id,
                    "content_hash": version.content_hash,
                    "typed_action_id": typed_action_id,
                    "tool_schema_name": tool_schema_name,
                    "tool_schema_version": tool_schema_version,
                    "canonical_params_json": canonical_params_json,
                    "canonical_params_hash": canonical_params_hash,
                    "active_resource_id": event.active_resource_id or f"replay-active-{proposal.id}",
                    "capability_name": version_payload["capability_name"],
                    "approved_at": event.created_at.isoformat(),
                }
            elif event.event_kind == "activation_result":
                existing = active.get(key)
                if existing is not None:
                    existing["active_resource_id"] = event.active_resource_id or existing["active_resource_id"]
            elif event.event_kind == "revocation_result":
                for candidate in [k for k in active if k[0] == proposal.id]:
                    active.pop(candidate, None)
        _ = now
        return list(active.values())
