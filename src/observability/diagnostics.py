from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import (
    ContextManifestRecord,
    ExecutionRunRecord,
    GlobalRunLeaseRecord,
    MessageAttachmentRecord,
    NodeExecutionAuditRecord,
    OutboundDeliveryAttemptRecord,
    OutboundDeliveryRecord,
    OutboxJobRecord,
    SessionRunLeaseRecord,
    SummarySnapshotRecord,
)
from src.domain.schemas import (
    DiagnosticsPageResponse,
    ExecutionRunResponse,
    RunDiagnosticsResponse,
    SessionContinuityDiagnosticsResponse,
)
from src.observability.redaction import bounded_preview


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def encode_cursor(created_at: datetime, row_id: Any) -> str:
    return f"{created_at.isoformat()}|{row_id}"


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    created_at, row_id = cursor.split("|", 1)
    return datetime.fromisoformat(created_at), row_id


@dataclass
class DiagnosticsService:
    settings: Settings
    delegation_service: Any | None = None

    def _resolve_limit(self, limit: int | None) -> int:
        return min(limit or self.settings.diagnostics_page_default_limit, self.settings.diagnostics_page_max_limit)

    def _apply_cursor(self, stmt: Select[Any], model, cursor: str | None):
        if not cursor:
            return stmt
        created_at, row_id = decode_cursor(cursor)
        return stmt.where(
            or_(
                model.created_at < created_at,
                and_(model.created_at == created_at, model.id < row_id),
            )
        )

    def list_runs(
        self,
        db: Session,
        *,
        limit: int | None,
        cursor: str | None,
        status: str | None,
        trigger_kind: str | None,
        session_id: str | None,
        agent_id: str | None,
        stale_only: bool,
        recent_seconds: int | None,
    ) -> DiagnosticsPageResponse:
        page_limit = self._resolve_limit(limit)
        stmt = select(ExecutionRunRecord)
        if status:
            stmt = stmt.where(ExecutionRunRecord.status == status)
        if trigger_kind:
            stmt = stmt.where(ExecutionRunRecord.trigger_kind == trigger_kind)
        if session_id:
            stmt = stmt.where(ExecutionRunRecord.session_id == session_id)
        if agent_id:
            stmt = stmt.where(ExecutionRunRecord.agent_id == agent_id)
        if stale_only:
            threshold = utc_now() - timedelta(seconds=self.settings.execution_run_stale_after_seconds)
            stmt = stmt.where(
                ExecutionRunRecord.status.in_(["claimed", "running"]),
                ExecutionRunRecord.updated_at <= threshold,
            )
        if recent_seconds:
            stmt = stmt.where(ExecutionRunRecord.created_at >= utc_now() - timedelta(seconds=recent_seconds))
        stmt = self._apply_cursor(stmt, ExecutionRunRecord, cursor)
        rows = list(
            db.scalars(
                stmt.order_by(ExecutionRunRecord.created_at.desc(), ExecutionRunRecord.id.desc()).limit(page_limit + 1)
            )
        )
        items = [ExecutionRunResponse.model_validate(row, from_attributes=True).model_dump(mode="json") for row in rows[:page_limit]]
        next_cursor = None
        if len(rows) > page_limit:
            marker = rows[page_limit - 1]
            next_cursor = encode_cursor(marker.created_at, marker.id)
        return DiagnosticsPageResponse(
            items=items,
            limit=page_limit,
            next_cursor=next_cursor,
            has_more=len(rows) > page_limit,
        )

    def get_run_detail(self, db: Session, *, run_id: str) -> RunDiagnosticsResponse | None:
        run = db.get(ExecutionRunRecord, run_id)
        if run is None:
            return None
        lane_lease = db.get(SessionRunLeaseRecord, run.lane_key)
        global_lease = db.scalar(select(GlobalRunLeaseRecord).where(GlobalRunLeaseRecord.execution_run_id == run.id))
        artifacts = {
            "outbox_job_ids": list(
                db.scalars(select(OutboxJobRecord.id).where(OutboxJobRecord.message_id == run.message_id).limit(10))
            ),
            "delivery_ids": list(
                db.scalars(select(OutboundDeliveryRecord.id).where(OutboundDeliveryRecord.execution_run_id == run.id).limit(10))
            ),
            "node_request_ids": list(
                db.scalars(
                    select(NodeExecutionAuditRecord.request_id).where(NodeExecutionAuditRecord.execution_run_id == run.id).limit(10)
                )
            ),
        }
        failures = [item for item in [run.last_error, run.degraded_reason] if item]
        delegation_payload = None
        if self.delegation_service is not None:
            if run.trigger_kind == "delegation_child":
                delegation = self.delegation_service.repository.get_by_child_run(db, child_run_id=run.id)
            elif run.trigger_kind == "delegation_result":
                delegation = self.delegation_service.repository.get_delegation(db, delegation_id=run.trigger_ref)
            else:
                delegation = None
            if delegation is not None:
                delegation_payload = {
                    "delegation_id": delegation.id,
                    "parent_session_id": delegation.parent_session_id,
                    "child_session_id": delegation.child_session_id,
                    "parent_run_id": delegation.parent_run_id,
                    "child_run_id": delegation.child_run_id,
                    "status": delegation.status,
                    "depth": delegation.depth,
                    "parent_result_run_id": delegation.parent_result_run_id,
                }
        return RunDiagnosticsResponse(
            run=ExecutionRunResponse.model_validate(run, from_attributes=True),
            lane_lease=None
            if lane_lease is None
            else {
                "worker_id": lane_lease.worker_id,
                "lease_expires_at": lane_lease.lease_expires_at,
            },
            global_lease=None
            if global_lease is None
            else {
                "worker_id": global_lease.worker_id,
                "lease_expires_at": global_lease.lease_expires_at,
            },
            recent_failures=failures[:5],
            execution_binding={
                "agent_id": run.agent_id,
                "model_profile_key": run.model_profile_key,
                "policy_profile_key": run.policy_profile_key,
                "tool_profile_key": run.tool_profile_key,
            },
            correlated_artifacts={**artifacts, **({} if delegation_payload is None else {"delegation": delegation_payload})},
        )

    def get_session_continuity(self, db: Session, *, session_id: str) -> SessionContinuityDiagnosticsResponse:
        summaries = list(
            db.scalars(
                select(SummarySnapshotRecord)
                .where(SummarySnapshotRecord.session_id == session_id)
                .order_by(SummarySnapshotRecord.created_at.desc(), SummarySnapshotRecord.id.desc())
                .limit(5)
            )
        )
        manifests = list(
            db.scalars(
                select(ContextManifestRecord)
                .where(ContextManifestRecord.session_id == session_id)
                .order_by(ContextManifestRecord.created_at.desc(), ContextManifestRecord.id.desc())
                .limit(5)
            )
        )
        pending_count = db.scalar(
            select(func.count()).select_from(OutboxJobRecord).where(
                OutboxJobRecord.session_id == session_id,
                OutboxJobRecord.status == "pending",
            )
        ) or 0
        failed_count = db.scalar(
            select(func.count()).select_from(OutboxJobRecord).where(
                OutboxJobRecord.session_id == session_id,
                OutboxJobRecord.status == "failed",
            )
        ) or 0
        recent_run_statuses = list(
            db.scalars(
                select(ExecutionRunRecord.status)
                .where(ExecutionRunRecord.session_id == session_id)
                .order_by(ExecutionRunRecord.created_at.desc(), ExecutionRunRecord.id.desc())
                .limit(5)
            )
        )
        return SessionContinuityDiagnosticsResponse(
            session_id=session_id,
            capability_status="enabled",
            summary_snapshot_count=len(summaries),
            latest_summary_created_at=summaries[0].created_at if summaries else None,
            context_manifest_count=len(manifests),
            latest_manifest_degraded=manifests[0].degraded if manifests else None,
            pending_outbox_jobs=pending_count,
            failed_outbox_jobs=failed_count,
            recent_run_statuses=recent_run_statuses,
        )

    def _page_model_rows(self, db: Session, *, stmt: Select[Any], model, limit: int | None, cursor: str | None, serializer):
        page_limit = self._resolve_limit(limit)
        stmt = self._apply_cursor(stmt, model, cursor)
        rows = list(db.scalars(stmt.order_by(model.created_at.desc(), model.id.desc()).limit(page_limit + 1)))
        items = [serializer(row) for row in rows[:page_limit]]
        next_cursor = None
        if len(rows) > page_limit:
            marker = rows[page_limit - 1]
            next_cursor = encode_cursor(marker.created_at, marker.id)
        return DiagnosticsPageResponse(items=items, limit=page_limit, next_cursor=next_cursor, has_more=len(rows) > page_limit)

    def list_outbox_jobs(self, db: Session, *, limit: int | None, cursor: str | None, status: str | None, stale_only: bool) -> DiagnosticsPageResponse:
        stmt = select(OutboxJobRecord)
        if status:
            stmt = stmt.where(OutboxJobRecord.status == status)
        if stale_only:
            threshold = utc_now() - timedelta(seconds=self.settings.outbox_job_stale_after_seconds)
            stmt = stmt.where(OutboxJobRecord.status == "running", OutboxJobRecord.updated_at <= threshold)
        return self._page_model_rows(
            db,
            stmt=stmt,
            model=OutboxJobRecord,
            limit=limit,
            cursor=cursor,
            serializer=lambda row: {
                "id": row.id,
                "session_id": row.session_id,
                "message_id": row.message_id,
                "job_kind": row.job_kind,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "trace_id": row.trace_id,
                "failure_category": row.failure_category,
                "last_error": bounded_preview(
                    row.last_error,
                    enabled=True,
                    max_chars=self.settings.observability_log_content_preview_chars,
                ),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            },
        )

    def list_node_executions(self, db: Session, *, limit: int | None, cursor: str | None, status: str | None, stale_only: bool) -> DiagnosticsPageResponse:
        stmt = select(NodeExecutionAuditRecord)
        if status:
            stmt = stmt.where(NodeExecutionAuditRecord.status == status)
        if stale_only:
            threshold = utc_now() - timedelta(seconds=self.settings.node_execution_stale_after_seconds)
            stmt = stmt.where(NodeExecutionAuditRecord.status.in_(["received", "running"]), NodeExecutionAuditRecord.updated_at <= threshold)
        return self._page_model_rows(
            db,
            stmt=stmt,
            model=NodeExecutionAuditRecord,
            limit=limit,
            cursor=cursor,
            serializer=lambda row: {
                "id": row.id,
                "request_id": row.request_id,
                "execution_run_id": row.execution_run_id,
                "status": row.status,
                "trace_id": row.trace_id,
                "sandbox_mode": row.sandbox_mode,
                "deny_reason": bounded_preview(
                    row.deny_reason,
                    enabled=True,
                    max_chars=self.settings.observability_log_content_preview_chars,
                ),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            },
        )

    def list_deliveries(self, db: Session, *, limit: int | None, cursor: str | None, status: str | None, stale_only: bool) -> DiagnosticsPageResponse:
        stmt = select(OutboundDeliveryRecord)
        if status:
            stmt = stmt.where(OutboundDeliveryRecord.status == status)
        if stale_only:
            threshold = utc_now() - timedelta(seconds=self.settings.outbound_delivery_stale_after_seconds)
            stmt = stmt.where(OutboundDeliveryRecord.status.not_in(["sent", "failed"]), OutboundDeliveryRecord.created_at <= threshold)
        return self._page_model_rows(
            db,
            stmt=stmt,
            model=OutboundDeliveryRecord,
            limit=limit,
            cursor=cursor,
            serializer=lambda row: {
                "id": row.id,
                "execution_run_id": row.execution_run_id,
                "channel_kind": row.channel_kind,
                "status": row.status,
                "trace_id": row.trace_id,
                "provider_message_id": row.provider_message_id,
                "failure_category": row.failure_category,
                "provider_metadata": json.loads(row.provider_metadata_json or "{}"),
                "payload": json.loads(row.delivery_payload_json or "{}"),
                "error_detail": bounded_preview(
                    row.error_detail,
                    enabled=True,
                    max_chars=self.settings.observability_log_content_preview_chars,
                ),
                "attempts": [
                    {
                        "id": attempt.id,
                        "status": attempt.status,
                        "trace_id": attempt.trace_id,
                        "error_detail": bounded_preview(
                            attempt.error_detail,
                            enabled=True,
                            max_chars=self.settings.observability_log_content_preview_chars,
                        ),
                    }
                    for attempt in db.scalars(
                        select(OutboundDeliveryAttemptRecord)
                        .where(OutboundDeliveryAttemptRecord.outbound_delivery_id == row.id)
                        .order_by(OutboundDeliveryAttemptRecord.attempt_number.desc(), OutboundDeliveryAttemptRecord.id.desc())
                        .limit(3)
                    )
                ],
                "created_at": row.created_at.isoformat(),
            },
        )

    def list_attachments(self, db: Session, *, limit: int | None, cursor: str | None, normalization_status: str | None, stale_only: bool) -> DiagnosticsPageResponse:
        stmt = select(MessageAttachmentRecord)
        if normalization_status:
            stmt = stmt.where(MessageAttachmentRecord.normalization_status == normalization_status)
        if stale_only:
            threshold = utc_now() - timedelta(seconds=self.settings.attachment_stale_after_seconds)
            stmt = stmt.where(MessageAttachmentRecord.normalization_status.in_(["pending", "failed"]), MessageAttachmentRecord.created_at <= threshold)
        return self._page_model_rows(
            db,
            stmt=stmt,
            model=MessageAttachmentRecord,
            limit=limit,
            cursor=cursor,
            serializer=lambda row: {
                "id": row.id,
                "session_id": row.session_id,
                "message_id": row.message_id,
                "normalization_status": row.normalization_status,
                "mime_type": row.mime_type,
                "storage_key": row.storage_key,
                "error_detail": bounded_preview(
                    row.error_detail,
                    enabled=True,
                    max_chars=self.settings.observability_log_content_preview_chars,
                ),
                "created_at": row.created_at.isoformat(),
            },
        )
