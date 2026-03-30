from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import DelegationEventRecord, DelegationRecord, DelegationStatus, MessageRecord
from src.jobs.repository import JobsRepository
from src.sessions.repository import SessionRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DelegationRepository:
    def __init__(
        self,
        *,
        session_repository: SessionRepository | None = None,
        jobs_repository: JobsRepository | None = None,
    ) -> None:
        self.session_repository = session_repository or SessionRepository()
        self.jobs_repository = jobs_repository or JobsRepository()

    def get_delegation(self, db: Session, *, delegation_id: str) -> DelegationRecord | None:
        return db.get(DelegationRecord, delegation_id)

    def get_by_parent_correlation(
        self,
        db: Session,
        *,
        parent_run_id: str,
        correlation_id: str,
    ) -> DelegationRecord | None:
        return db.scalar(
            select(DelegationRecord).where(
                DelegationRecord.parent_run_id == parent_run_id,
                DelegationRecord.parent_tool_call_correlation_id == correlation_id,
            )
        )

    def get_by_child_run(self, db: Session, *, child_run_id: str) -> DelegationRecord | None:
        return db.scalar(select(DelegationRecord).where(DelegationRecord.child_run_id == child_run_id))

    def get_by_child_session(self, db: Session, *, child_session_id: str) -> DelegationRecord | None:
        return db.scalar(select(DelegationRecord).where(DelegationRecord.child_session_id == child_session_id))

    def list_by_parent_session(self, db: Session, *, session_id: str) -> list[DelegationRecord]:
        return list(
            db.scalars(
                select(DelegationRecord)
                .where(DelegationRecord.parent_session_id == session_id)
                .order_by(DelegationRecord.created_at.desc(), DelegationRecord.id.desc())
            )
        )

    def list_by_child_agent(self, db: Session, *, agent_id: str) -> list[DelegationRecord]:
        return list(
            db.scalars(
                select(DelegationRecord)
                .where(DelegationRecord.child_agent_id == agent_id)
                .order_by(DelegationRecord.created_at.desc(), DelegationRecord.id.desc())
            )
        )

    def list_events(self, db: Session, *, delegation_id: str) -> list[DelegationEventRecord]:
        return list(
            db.scalars(
                select(DelegationEventRecord)
                .where(DelegationEventRecord.delegation_id == delegation_id)
                .order_by(DelegationEventRecord.id.asc())
            )
        )

    def count_active_for_parent_run(self, db: Session, *, parent_run_id: str) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(DelegationRecord).where(
                    DelegationRecord.parent_run_id == parent_run_id,
                    DelegationRecord.status.in_(
                        [
                            DelegationStatus.QUEUED.value,
                            DelegationStatus.RUNNING.value,
                            DelegationStatus.AWAITING_APPROVAL.value,
                        ]
                    ),
                )
            )
            or 0
        )

    def count_active_for_parent_session(self, db: Session, *, parent_session_id: str) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(DelegationRecord).where(
                    DelegationRecord.parent_session_id == parent_session_id,
                    DelegationRecord.status.in_(
                        [
                            DelegationStatus.QUEUED.value,
                            DelegationStatus.RUNNING.value,
                            DelegationStatus.AWAITING_APPROVAL.value,
                        ]
                    ),
                )
            )
            or 0
        )

    def create_delegation(
        self,
        db: Session,
        *,
        delegation_id: str,
        parent_session_id: str,
        parent_message_id: int,
        parent_run_id: str,
        parent_tool_call_correlation_id: str,
        parent_agent_id: str,
        child_session_id: str,
        child_message_id: int,
        child_run_id: str,
        child_agent_id: str,
        status: str,
        depth: int,
        delegation_kind: str,
        task_text: str,
        context_payload: dict[str, Any],
        queued_at: datetime | None = None,
    ) -> DelegationRecord:
        record = DelegationRecord(
            id=delegation_id,
            parent_session_id=parent_session_id,
            parent_message_id=parent_message_id,
            parent_run_id=parent_run_id,
            parent_tool_call_correlation_id=parent_tool_call_correlation_id,
            parent_agent_id=parent_agent_id,
            child_session_id=child_session_id,
            child_message_id=child_message_id,
            child_run_id=child_run_id,
            child_agent_id=child_agent_id,
            status=status,
            depth=depth,
            delegation_kind=delegation_kind,
            task_text=task_text,
            context_payload_json=json.dumps(context_payload, sort_keys=True),
            queued_at=queued_at or utc_now(),
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = self.get_by_parent_correlation(
                db,
                parent_run_id=parent_run_id,
                correlation_id=parent_tool_call_correlation_id,
            )
            if existing is None:
                raise
            return existing
        return record

    def append_event(
        self,
        db: Session,
        *,
        delegation_id: str,
        event_kind: str,
        status: str,
        actor_kind: str,
        actor_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DelegationEventRecord:
        event = DelegationEventRecord(
            delegation_id=delegation_id,
            event_kind=event_kind,
            status=status,
            actor_kind=actor_kind,
            actor_ref=actor_ref,
            payload_json=json.dumps(payload or {}, sort_keys=True),
        )
        db.add(event)
        db.flush()
        return event

    def mark_running(
        self,
        db: Session,
        *,
        delegation_id: str,
        started_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        record.status = DelegationStatus.RUNNING.value
        record.started_at = started_at or utc_now()
        record.updated_at = record.started_at
        db.flush()
        return record

    def mark_awaiting_approval(
        self,
        db: Session,
        *,
        delegation_id: str,
        awaiting_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        record.status = DelegationStatus.AWAITING_APPROVAL.value
        record.updated_at = awaiting_at or utc_now()
        db.flush()
        return record

    def requeue_child_run(
        self,
        db: Session,
        *,
        delegation_id: str,
        child_message_id: int,
        child_run_id: str,
        queued_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        current_time = queued_at or utc_now()
        record.child_message_id = child_message_id
        record.child_run_id = child_run_id
        record.status = DelegationStatus.QUEUED.value
        record.failure_detail = None
        record.completed_at = None
        record.started_at = None
        record.parent_result_message_id = None
        record.parent_result_run_id = None
        record.updated_at = current_time
        db.flush()
        return record

    def mark_completed(
        self,
        db: Session,
        *,
        delegation_id: str,
        result_payload: dict[str, Any],
        parent_result_message_id: int | None,
        parent_result_run_id: str | None,
        completed_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        current_time = completed_at or utc_now()
        record.status = DelegationStatus.COMPLETED.value
        record.result_payload_json = json.dumps(result_payload, sort_keys=True)
        record.parent_result_message_id = parent_result_message_id
        record.parent_result_run_id = parent_result_run_id
        record.completed_at = current_time
        record.updated_at = current_time
        db.flush()
        return record

    def mark_failed(
        self,
        db: Session,
        *,
        delegation_id: str,
        failure_detail: str,
        completed_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        current_time = completed_at or utc_now()
        record.status = DelegationStatus.FAILED.value
        record.failure_detail = failure_detail
        record.completed_at = current_time
        record.updated_at = current_time
        db.flush()
        return record

    def mark_cancelled(
        self,
        db: Session,
        *,
        delegation_id: str,
        cancel_reason: str,
        completed_at: datetime | None = None,
    ) -> DelegationRecord:
        record = self._require(db, delegation_id=delegation_id)
        current_time = completed_at or utc_now()
        record.status = DelegationStatus.CANCELLED.value
        record.cancel_reason = cancel_reason
        record.completed_at = current_time
        record.updated_at = current_time
        db.flush()
        return record

    def create_or_get_parent_result_message(
        self,
        db: Session,
        *,
        delegation: DelegationRecord,
        sender_id: str,
        content: str,
    ) -> MessageRecord:
        if delegation.parent_result_message_id is not None:
            existing = self.session_repository.get_message(db, message_id=delegation.parent_result_message_id)
            if existing is not None:
                return existing
        parent_session = self.session_repository.get_session(db, delegation.parent_session_id)
        if parent_session is None:
            raise RuntimeError("parent session missing for delegation continuation")
        message = self.session_repository.append_message(
            db,
            parent_session,
            role="system",
            content=content,
            external_message_id=None,
            sender_id=sender_id,
            last_activity_at=utc_now(),
        )
        delegation.parent_result_message_id = message.id
        db.flush()
        return message

    def create_or_get_parent_result_run(
        self,
        db: Session,
        *,
        delegation: DelegationRecord,
        parent_result_message_id: int,
        agent_id: str,
        model_profile_key: str,
        policy_profile_key: str,
        tool_profile_key: str,
        max_attempts: int,
        status: str = "queued",
        blocked_reason: str | None = None,
    ):
        run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=delegation.parent_session_id,
            message_id=parent_result_message_id,
            agent_id=agent_id,
            model_profile_key=model_profile_key,
            policy_profile_key=policy_profile_key,
            tool_profile_key=tool_profile_key,
            trigger_kind="delegation_result",
            trigger_ref=delegation.id,
            lane_key=delegation.parent_session_id,
            max_attempts=max_attempts,
            status=status,
            blocked_reason=blocked_reason,
        )
        delegation.parent_result_run_id = run.id
        db.flush()
        return run

    def _require(self, db: Session, *, delegation_id: str) -> DelegationRecord:
        record = self.get_delegation(db, delegation_id=delegation_id)
        if record is None:
            raise RuntimeError("delegation not found")
        return record
