from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import (
    ExecutionRunRecord,
    ExecutionRunStatus,
    GlobalRunLeaseRecord,
    ScheduledJobFireRecord,
    ScheduledJobRecord,
    SessionRunLeaseRecord,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class QueueClaim:
    run: ExecutionRunRecord
    lease_expires_at: datetime


class JobsRepository:
    def create_or_get_execution_run(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int | None,
        agent_id: str,
        model_profile_key: str = "default",
        policy_profile_key: str = "default",
        tool_profile_key: str = "default",
        trigger_kind: str,
        trigger_ref: str,
        lane_key: str,
        max_attempts: int,
        status: str = ExecutionRunStatus.QUEUED.value,
        blocked_reason: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionRunRecord:
        current_time = now or utc_now()
        existing = self.get_execution_run_by_trigger(
            db,
            trigger_kind=trigger_kind,
            trigger_ref=trigger_ref,
        )
        if existing is not None:
            if existing.trace_id is None:
                existing.trace_id = uuid4().hex
                existing.correlation_id = existing.trace_id
                existing.updated_at = current_time
                db.flush()
            return existing

        run = ExecutionRunRecord(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            model_profile_key=model_profile_key,
            policy_profile_key=policy_profile_key,
            tool_profile_key=tool_profile_key,
            trigger_kind=trigger_kind,
            trigger_ref=trigger_ref,
            lane_key=lane_key,
            status=status,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=current_time,
            blocked_reason=blocked_reason,
            blocked_at=current_time if status == ExecutionRunStatus.BLOCKED.value else None,
            trace_id=uuid4().hex,
        )
        run.correlation_id = run.trace_id
        db.add(run)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = self.get_execution_run_by_trigger(
                db,
                trigger_kind=trigger_kind,
                trigger_ref=trigger_ref,
            )
            if existing is None:
                raise
            if existing.trace_id is None:
                existing.trace_id = uuid4().hex
                existing.correlation_id = existing.trace_id
                existing.updated_at = current_time
                db.flush()
            return existing
        return run

    def get_execution_run(self, db: Session, run_id: str) -> ExecutionRunRecord | None:
        return db.get(ExecutionRunRecord, run_id)

    def get_execution_run_by_trigger(
        self,
        db: Session,
        *,
        trigger_kind: str,
        trigger_ref: str,
    ) -> ExecutionRunRecord | None:
        return db.scalar(
            select(ExecutionRunRecord).where(
                ExecutionRunRecord.trigger_kind == trigger_kind,
                ExecutionRunRecord.trigger_ref == trigger_ref,
            )
        )

    def list_session_runs(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int,
    ) -> list[ExecutionRunRecord]:
        return list(
            db.scalars(
                select(ExecutionRunRecord)
                .where(ExecutionRunRecord.session_id == session_id)
                .order_by(ExecutionRunRecord.created_at.desc(), ExecutionRunRecord.id.desc())
                .limit(limit)
            )
        )

    def claim_next_eligible_run(
        self,
        db: Session,
        *,
        worker_id: str,
        lease_seconds: int,
        global_concurrency_limit: int,
        now: datetime | None = None,
    ) -> QueueClaim | None:
        current_time = now or utc_now()
        self.recover_expired_leases(db, now=current_time)
        if global_concurrency_limit <= 0:
            return None

        rows = list(
            db.scalars(
                select(ExecutionRunRecord)
                .where(
                    ExecutionRunRecord.status.in_(
                        [ExecutionRunStatus.QUEUED.value, ExecutionRunStatus.RETRY_WAIT.value]
                    ),
                    ExecutionRunRecord.available_at <= current_time,
                )
                .order_by(
                    ExecutionRunRecord.available_at.asc(),
                    ExecutionRunRecord.created_at.asc(),
                    ExecutionRunRecord.id.asc(),
                )
            )
        )
        blocked_lanes: set[str] = set()
        for run in rows:
            if run.lane_key in blocked_lanes:
                continue
            lease_expires_at = self.acquire_session_lease(
                db,
                lane_key=run.lane_key,
                execution_run_id=run.id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=current_time,
            )
            if lease_expires_at is None:
                blocked_lanes.add(run.lane_key)
                continue
            global_lease_expires_at = self.acquire_global_slot(
                db,
                execution_run_id=run.id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                global_concurrency_limit=global_concurrency_limit,
                now=current_time,
            )
            if global_lease_expires_at is None:
                self.release_session_lease(
                    db,
                    lane_key=run.lane_key,
                    execution_run_id=run.id,
                    worker_id=worker_id,
                )
                return None
            claimed = self._transition_to_claimed(
                db,
                run_id=run.id,
                worker_id=worker_id,
                current_time=current_time,
            )
            if claimed is None:
                self.release_session_lease(db, lane_key=run.lane_key, execution_run_id=run.id, worker_id=worker_id)
                self.release_global_slot(db, execution_run_id=run.id, worker_id=worker_id)
                continue
            return QueueClaim(run=claimed, lease_expires_at=lease_expires_at)
        return None

    def _transition_to_claimed(
        self,
        db: Session,
        *,
        run_id: str,
        worker_id: str,
        current_time: datetime,
    ) -> ExecutionRunRecord | None:
        result = db.execute(
            update(ExecutionRunRecord)
            .where(
                ExecutionRunRecord.id == run_id,
                ExecutionRunRecord.status.in_(
                    [ExecutionRunStatus.QUEUED.value, ExecutionRunStatus.RETRY_WAIT.value]
                ),
            )
            .values(
                status=ExecutionRunStatus.CLAIMED.value,
                worker_id=worker_id,
                claimed_at=current_time,
                updated_at=current_time,
            )
        )
        if result.rowcount != 1:
            return None
        return db.get(ExecutionRunRecord, run_id)

    def mark_running(
        self,
        db: Session,
        *,
        run_id: str,
        worker_id: str,
        started_at: datetime | None = None,
    ) -> ExecutionRunRecord:
        current_time = started_at or utc_now()
        run = db.get(ExecutionRunRecord, run_id)
        if run is None:
            raise RuntimeError("execution run not found")
        run.status = ExecutionRunStatus.RUNNING.value
        run.worker_id = worker_id
        run.started_at = current_time
        run.updated_at = current_time
        db.flush()
        return run

    def release_blocked_runs(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> list[ExecutionRunRecord]:
        current_time = now or utc_now()
        stmt = (
            select(ExecutionRunRecord)
            .where(
                ExecutionRunRecord.session_id == session_id,
                ExecutionRunRecord.status == ExecutionRunStatus.BLOCKED.value,
            )
            .order_by(ExecutionRunRecord.created_at.asc(), ExecutionRunRecord.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = list(db.scalars(stmt))
        for run in rows:
            run.status = ExecutionRunStatus.QUEUED.value
            run.blocked_reason = None
            run.blocked_at = None
            run.available_at = current_time
            run.updated_at = current_time
        db.flush()
        return rows

    def complete_run(
        self,
        db: Session,
        *,
        run_id: str,
        worker_id: str,
        finished_at: datetime | None = None,
    ) -> ExecutionRunRecord:
        current_time = finished_at or utc_now()
        run = self._get_owned_run(db, run_id=run_id, worker_id=worker_id)
        run.status = ExecutionRunStatus.COMPLETED.value
        run.finished_at = current_time
        run.updated_at = current_time
        db.flush()
        return run

    def fail_run(
        self,
        db: Session,
        *,
        run_id: str,
        worker_id: str,
        error: str,
        finished_at: datetime | None = None,
    ) -> ExecutionRunRecord:
        current_time = finished_at or utc_now()
        run = self._get_owned_run(db, run_id=run_id, worker_id=worker_id)
        run.status = ExecutionRunStatus.FAILED.value
        run.finished_at = current_time
        run.last_error = error
        run.failure_category = "unexpected_internal"
        run.updated_at = current_time
        db.flush()
        return run

    def retry_run(
        self,
        db: Session,
        *,
        run_id: str,
        worker_id: str,
        error: str,
        backoff_seconds: int,
        finished_at: datetime | None = None,
    ) -> ExecutionRunRecord:
        current_time = finished_at or utc_now()
        run = self._get_owned_run(db, run_id=run_id, worker_id=worker_id)
        run.attempt_count += 1
        run.status = (
            ExecutionRunStatus.DEAD_LETTER.value
            if run.attempt_count >= run.max_attempts
            else ExecutionRunStatus.RETRY_WAIT.value
        )
        run.available_at = current_time + timedelta(seconds=backoff_seconds)
        run.last_error = error
        run.failure_category = "unexpected_internal"
        run.finished_at = current_time if run.status == ExecutionRunStatus.DEAD_LETTER.value else None
        run.updated_at = current_time
        db.flush()
        return run

    def acquire_session_lease(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> datetime | None:
        current_time = now or utc_now()
        expires_at = current_time + timedelta(seconds=lease_seconds)
        existing = db.get(SessionRunLeaseRecord, lane_key)
        if existing is None:
            lease = SessionRunLeaseRecord(
                lane_key=lane_key,
                execution_run_id=execution_run_id,
                worker_id=worker_id,
                lease_expires_at=expires_at,
            )
            db.add(lease)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return self.acquire_session_lease(
                    db,
                    lane_key=lane_key,
                    execution_run_id=execution_run_id,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now=current_time,
                )
            return expires_at

        if existing.execution_run_id == execution_run_id and existing.worker_id == worker_id:
            existing.lease_expires_at = expires_at
            existing.updated_at = current_time
            db.flush()
            return expires_at

        if as_utc(existing.lease_expires_at) > current_time:
            return None

        leased_run = db.get(ExecutionRunRecord, existing.execution_run_id)
        if leased_run is not None:
            self._recover_expired_execution_run(
                db,
                run=leased_run,
                error="session lane lease expired before terminal persistence",
                current_time=current_time,
            )
        existing.execution_run_id = execution_run_id
        existing.worker_id = worker_id
        existing.lease_expires_at = expires_at
        existing.updated_at = current_time
        db.flush()
        return expires_at

    def refresh_session_lease(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> datetime | None:
        current_time = now or utc_now()
        lease = db.get(SessionRunLeaseRecord, lane_key)
        if lease is None:
            return None
        if lease.execution_run_id != execution_run_id or lease.worker_id != worker_id:
            return None
        lease.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
        lease.updated_at = current_time
        db.flush()
        return lease.lease_expires_at

    def release_session_lease(
        self,
        db: Session,
        *,
        lane_key: str,
        execution_run_id: str,
        worker_id: str,
    ) -> None:
        lease = db.get(SessionRunLeaseRecord, lane_key)
        if lease is None:
            return
        if lease.execution_run_id != execution_run_id or lease.worker_id != worker_id:
            return
        db.delete(lease)
        db.flush()

    def acquire_global_slot(
        self,
        db: Session,
        *,
        execution_run_id: str,
        worker_id: str,
        lease_seconds: int,
        global_concurrency_limit: int,
        now: datetime | None = None,
    ) -> datetime | None:
        current_time = now or utc_now()
        expires_at = current_time + timedelta(seconds=lease_seconds)
        for slot_number in range(global_concurrency_limit):
            slot_key = str(slot_number)
            existing = db.get(GlobalRunLeaseRecord, slot_key)
            if existing is None:
                lease = GlobalRunLeaseRecord(
                    slot_key=slot_key,
                    execution_run_id=execution_run_id,
                    worker_id=worker_id,
                    lease_expires_at=expires_at,
                )
                db.add(lease)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    return self.acquire_global_slot(
                        db,
                        execution_run_id=execution_run_id,
                        worker_id=worker_id,
                        lease_seconds=lease_seconds,
                        global_concurrency_limit=global_concurrency_limit,
                        now=current_time,
                    )
                return expires_at

            if existing.execution_run_id == execution_run_id and existing.worker_id == worker_id:
                existing.lease_expires_at = expires_at
                existing.updated_at = current_time
                db.flush()
                return expires_at

            if as_utc(existing.lease_expires_at) > current_time:
                continue

            leased_run = db.get(ExecutionRunRecord, existing.execution_run_id)
            if leased_run is not None:
                self._recover_expired_execution_run(
                    db,
                    run=leased_run,
                    error="global execution slot expired before terminal persistence",
                    current_time=current_time,
                )
            existing.execution_run_id = execution_run_id
            existing.worker_id = worker_id
            existing.lease_expires_at = expires_at
            existing.updated_at = current_time
            db.flush()
            return expires_at
        return None

    def refresh_global_slot(
        self,
        db: Session,
        *,
        execution_run_id: str,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> datetime | None:
        current_time = now or utc_now()
        lease = db.scalar(
            select(GlobalRunLeaseRecord).where(
                GlobalRunLeaseRecord.execution_run_id == execution_run_id,
                GlobalRunLeaseRecord.worker_id == worker_id,
            )
        )
        if lease is None:
            return None
        lease.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
        lease.updated_at = current_time
        db.flush()
        return lease.lease_expires_at

    def release_global_slot(
        self,
        db: Session,
        *,
        execution_run_id: str,
        worker_id: str,
    ) -> None:
        lease = db.scalar(
            select(GlobalRunLeaseRecord).where(
                GlobalRunLeaseRecord.execution_run_id == execution_run_id,
                GlobalRunLeaseRecord.worker_id == worker_id,
            )
        )
        if lease is None:
            return
        db.delete(lease)
        db.flush()

    def recover_expired_leases(self, db: Session, *, now: datetime | None = None) -> None:
        current_time = now or utc_now()
        expired_session_leases = list(
            lease
            for lease in db.scalars(select(SessionRunLeaseRecord))
            if as_utc(lease.lease_expires_at) <= current_time
        )
        for lease in expired_session_leases:
            run = db.get(ExecutionRunRecord, lease.execution_run_id)
            if run is not None:
                self._recover_expired_execution_run(
                    db,
                    run=run,
                    error="session lane lease expired before terminal persistence",
                    current_time=current_time,
                )
            db.delete(lease)

        expired_global_slots = list(
            lease
            for lease in db.scalars(select(GlobalRunLeaseRecord))
            if as_utc(lease.lease_expires_at) <= current_time
        )
        for lease in expired_global_slots:
            run = db.get(ExecutionRunRecord, lease.execution_run_id)
            if run is not None:
                self._recover_expired_execution_run(
                    db,
                    run=run,
                    error="global execution slot expired before terminal persistence",
                    current_time=current_time,
                )
            db.delete(lease)
        db.flush()

    def list_enabled_scheduled_jobs(self, db: Session) -> list[ScheduledJobRecord]:
        return list(
            db.scalars(
                select(ScheduledJobRecord).where(ScheduledJobRecord.enabled == 1).order_by(ScheduledJobRecord.job_key.asc())
            )
        )

    def create_or_get_scheduled_fire(
        self,
        db: Session,
        *,
        scheduled_job_id: str,
        fire_key: str,
        scheduled_for: datetime,
    ) -> ScheduledJobFireRecord:
        existing = db.scalar(
            select(ScheduledJobFireRecord).where(ScheduledJobFireRecord.fire_key == fire_key)
        )
        if existing is not None:
            return existing
        fire = ScheduledJobFireRecord(
            scheduled_job_id=scheduled_job_id,
            fire_key=fire_key,
            scheduled_for=scheduled_for,
            status="queued",
        )
        db.add(fire)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(
                select(ScheduledJobFireRecord).where(ScheduledJobFireRecord.fire_key == fire_key)
            )
            if existing is None:
                raise
            return existing
        return fire

    def link_fire_to_run(
        self,
        db: Session,
        *,
        fire_id: str,
        run_id: str,
        status: str = "submitted",
    ) -> ScheduledJobFireRecord:
        fire = db.get(ScheduledJobFireRecord, fire_id)
        if fire is None:
            raise RuntimeError("scheduled fire not found")
        fire.execution_run_id = run_id
        fire.status = status
        fire.updated_at = utc_now()
        db.flush()
        return fire

    def mark_fire_terminal(
        self,
        db: Session,
        *,
        fire_id: str,
        status: str,
        error: str | None = None,
    ) -> ScheduledJobFireRecord:
        fire = db.get(ScheduledJobFireRecord, fire_id)
        if fire is None:
            raise RuntimeError("scheduled fire not found")
        fire.status = status
        fire.last_error = error
        fire.updated_at = utc_now()
        db.flush()
        return fire

    def mark_fire_by_key(
        self,
        db: Session,
        *,
        fire_key: str,
        status: str,
        error: str | None = None,
    ) -> ScheduledJobFireRecord | None:
        fire = db.scalar(select(ScheduledJobFireRecord).where(ScheduledJobFireRecord.fire_key == fire_key))
        if fire is None:
            return None
        fire.status = status
        fire.last_error = error
        fire.updated_at = utc_now()
        db.flush()
        return fire

    def _get_owned_run(self, db: Session, *, run_id: str, worker_id: str) -> ExecutionRunRecord:
        run = db.get(ExecutionRunRecord, run_id)
        if run is None:
            raise RuntimeError("execution run not found")
        if run.worker_id != worker_id:
            raise RuntimeError("execution run is not owned by worker")
        return run

    def _recover_expired_execution_run(
        self,
        db: Session,
        *,
        run: ExecutionRunRecord,
        error: str,
        current_time: datetime,
    ) -> ExecutionRunRecord:
        if run.status not in {ExecutionRunStatus.CLAIMED.value, ExecutionRunStatus.RUNNING.value}:
            return run
        run.attempt_count += 1
        run.worker_id = None
        run.last_error = error
        run.available_at = min(as_utc(run.available_at), current_time)
        run.updated_at = current_time
        if run.attempt_count >= run.max_attempts:
            run.status = ExecutionRunStatus.DEAD_LETTER.value
            run.finished_at = current_time
        else:
            run.status = ExecutionRunStatus.RETRY_WAIT.value
            run.finished_at = None
        db.flush()
        return run
