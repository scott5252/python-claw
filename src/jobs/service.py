from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from src.graphs.assistant_graph import AssistantGraph
from src.jobs.repository import JobsRepository
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    reason: str


class FailureClassifier:
    def classify(self, exc: Exception) -> RetryDecision:
        if isinstance(exc, RuntimeError):
            return RetryDecision(retryable=False, reason=str(exc))
        return RetryDecision(retryable=True, reason=str(exc))


@dataclass
class RunExecutionService:
    jobs_repository: JobsRepository
    session_repository: SessionRepository
    concurrency_service: SessionConcurrencyService
    assistant_graph_factory: Callable[[], AssistantGraph]
    failure_classifier: FailureClassifier
    base_backoff_seconds: int
    max_backoff_seconds: int

    def process_next_run(self, db: Session, *, worker_id: str | None = None) -> str | None:
        resolved_worker_id = worker_id or f"{socket.gethostname()}-worker"
        claim = self.jobs_repository.claim_next_eligible_run(
            db,
            worker_id=resolved_worker_id,
            lease_seconds=self.concurrency_service.lease_seconds,
            global_concurrency_limit=self.concurrency_service.global_concurrency_limit,
        )
        if claim is None:
            return None

        run = claim.run
        try:
            self.jobs_repository.mark_running(db, run_id=run.id, worker_id=resolved_worker_id)
            self.concurrency_service.refresh_lane(
                db,
                lane_key=run.lane_key,
                execution_run_id=run.id,
                worker_id=resolved_worker_id,
                now=utc_now(),
            )
            self.concurrency_service.refresh_global_slot(
                db,
                execution_run_id=run.id,
                worker_id=resolved_worker_id,
                now=utc_now(),
            )
            graph = self.assistant_graph_factory()
            message = self.session_repository.get_message(db, message_id=run.message_id) if run.message_id else None
            if message is None:
                raise RuntimeError("missing canonical transcript state for execution run")
            state = graph.invoke(
                db=db,
                session_id=run.session_id,
                message_id=message.id,
                agent_id=run.agent_id,
                channel_kind=self.session_repository.get_session_channel_kind(db, session_id=run.session_id),
                sender_id=message.sender_id,
                user_text=message.content,
            )
            self._enqueue_after_turn_jobs(
                db,
                session_id=run.session_id,
                message_id=message.id,
                degraded=state.degraded,
            )
            self.jobs_repository.complete_run(db, run_id=run.id, worker_id=resolved_worker_id)
            if run.trigger_kind == "scheduler_fire":
                self.jobs_repository.mark_fire_by_key(db, fire_key=run.trigger_ref, status="completed")
            return run.id
        except Exception as exc:
            decision = self.failure_classifier.classify(exc)
            if decision.retryable:
                updated_run = self.jobs_repository.retry_run(
                    db,
                    run_id=run.id,
                    worker_id=resolved_worker_id,
                    error=decision.reason,
                    backoff_seconds=self._backoff_seconds(run.attempt_count),
                )
                if run.trigger_kind == "scheduler_fire" and updated_run.status == "dead_letter":
                    self.jobs_repository.mark_fire_by_key(
                        db,
                        fire_key=run.trigger_ref,
                        status="failed",
                        error=decision.reason,
                    )
            else:
                self.jobs_repository.fail_run(
                    db,
                    run_id=run.id,
                    worker_id=resolved_worker_id,
                    error=decision.reason,
                )
                if run.trigger_kind == "scheduler_fire":
                    self.jobs_repository.mark_fire_by_key(
                        db,
                        fire_key=run.trigger_ref,
                        status="failed",
                        error=decision.reason,
                    )
            return run.id
        finally:
            self.concurrency_service.release_lane(
                db,
                lane_key=run.lane_key,
                execution_run_id=run.id,
                worker_id=resolved_worker_id,
            )
            self.concurrency_service.release_global_slot(
                db,
                execution_run_id=run.id,
                worker_id=resolved_worker_id,
            )

    def _backoff_seconds(self, attempt_count: int) -> int:
        return min(self.base_backoff_seconds * (2 ** max(attempt_count, 0)), self.max_backoff_seconds)

    def _enqueue_after_turn_jobs(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        degraded: bool,
    ) -> None:
        self.session_repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="summary_generation",
            job_dedupe_key=f"summary_generation:{session_id}:{message_id}",
        )
        self.session_repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="retrieval_index",
            job_dedupe_key=f"retrieval_index:{session_id}:{message_id}",
        )
        if degraded:
            self.session_repository.enqueue_outbox_job(
                db,
                session_id=session_id,
                message_id=message_id,
                job_kind="continuity_repair",
                job_dedupe_key=f"continuity_repair:{session_id}:{message_id}",
            )


@dataclass
class SchedulerService:
    jobs_repository: JobsRepository
    session_repository: SessionRepository
    submit_scheduler_run: Callable[..., tuple[str, str]]

    def submit_due_job(
        self,
        db: Session,
        *,
        job_key: str,
        scheduled_for: datetime,
    ) -> str:
        job = self.session_repository.get_scheduled_job_by_key(db, job_key=job_key)
        if job is None:
            raise RuntimeError("scheduled job not found")
        fire_key = f"{job.job_key}:{scheduled_for.isoformat()}"
        fire = self.jobs_repository.create_or_get_scheduled_fire(
            db,
            scheduled_job_id=job.id,
            fire_key=fire_key,
            scheduled_for=scheduled_for,
        )
        job.last_fired_at = scheduled_for
        payload = json.loads(job.payload_json)
        run_id, _ = self.submit_scheduler_run(
            db=db,
            scheduled_job=job,
            fire=fire,
            payload=payload,
        )
        self.jobs_repository.link_fire_to_run(db, fire_id=fire.id, run_id=run_id)
        return run_id
