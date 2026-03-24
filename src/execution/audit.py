from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.models import NodeExecutionAuditRecord, NodeExecutionStatus
from src.execution.contracts import NodeExecRequest, preview_text
from src.policies.service import hash_payload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ExecutionAuditRepository:
    def insert_or_get(self, db: Session, *, request: NodeExecRequest) -> tuple[NodeExecutionAuditRecord, bool]:
        existing = self.get_by_request_id(db, request_id=request.request_id)
        if existing is not None:
            return existing, False
        record = NodeExecutionAuditRecord(
            request_id=request.request_id,
            execution_run_id=request.execution_run_id,
            tool_call_id=request.tool_call_id,
            execution_attempt_number=request.execution_attempt_number,
            message_id=request.message_id,
            session_id=request.session_id,
            agent_id=request.agent_id,
            requester_kind="graph_turn",
            sandbox_mode=request.sandbox_mode,
            sandbox_key=request.sandbox_key,
            workspace_root=request.workspace_root,
            workspace_mount_mode=request.workspace_mount_mode,
            command_fingerprint=hash_payload("|".join(request.argv)),
            typed_action_id=request.typed_action_id,
            approval_id=request.approval_id,
            resource_version_id=request.resource_version_id,
            status=NodeExecutionStatus.RECEIVED.value,
            trace_id=request.trace_id,
        )
        db.add(record)
        db.flush()
        return record, True

    def get_by_request_id(self, db: Session, *, request_id: str) -> NodeExecutionAuditRecord | None:
        return db.query(NodeExecutionAuditRecord).filter(NodeExecutionAuditRecord.request_id == request_id).one_or_none()

    def mark_rejected(self, db: Session, *, record: NodeExecutionAuditRecord, reason: str) -> NodeExecutionAuditRecord:
        record.status = NodeExecutionStatus.REJECTED.value
        record.deny_reason = reason
        record.finished_at = utc_now()
        record.updated_at = record.finished_at
        db.flush()
        return record

    def mark_running(self, db: Session, *, record: NodeExecutionAuditRecord) -> NodeExecutionAuditRecord:
        now = utc_now()
        record.status = NodeExecutionStatus.RUNNING.value
        record.started_at = now
        record.updated_at = now
        db.flush()
        return record

    def mark_finished(
        self,
        db: Session,
        *,
        record: NodeExecutionAuditRecord,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
    ) -> NodeExecutionAuditRecord:
        finished_at = utc_now()
        stdout_preview, stdout_truncated = preview_text(stdout)
        stderr_preview, stderr_truncated = preview_text(stderr)
        record.status = status
        record.exit_code = exit_code
        record.stdout_preview = stdout_preview
        record.stderr_preview = stderr_preview
        record.stdout_truncated = stdout_truncated
        record.stderr_truncated = stderr_truncated
        record.finished_at = finished_at
        record.updated_at = finished_at
        if record.started_at is not None:
            record.duration_ms = max(int((finished_at - record.started_at).total_seconds() * 1000), 0)
        db.flush()
        return record
