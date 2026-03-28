from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import logging

from sqlalchemy.orm import Session

from src.agents.repository import AgentRepository
from src.agents.service import AgentExecutionBinding, AgentProfileService
from src.graphs.assistant_graph import AssistantGraph
from src.jobs.repository import JobsRepository
from src.observability.failures import classify_failure
from src.observability.logging import build_event, emit_event
from src.providers.models import ProviderError
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository
from src.config.settings import Settings

logger = logging.getLogger(__name__)

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    reason: str


class FailureClassifier:
    def classify(self, exc: Exception) -> RetryDecision:
        if isinstance(exc, ProviderError):
            return RetryDecision(retryable=exc.retryable, reason=exc.detail)
        if isinstance(exc, RuntimeError):
            return RetryDecision(retryable=False, reason=str(exc))
        return RetryDecision(retryable=True, reason=str(exc))


@dataclass
class RunExecutionService:
    jobs_repository: JobsRepository
    session_repository: SessionRepository
    concurrency_service: SessionConcurrencyService
    assistant_graph_factory: Callable[[AgentExecutionBinding], AssistantGraph]
    failure_classifier: FailureClassifier
    base_backoff_seconds: int
    max_backoff_seconds: int
    agent_profile_service: AgentProfileService | None = None
    media_processor: object | None = None
    attachment_extraction_service: object | None = None
    outbound_dispatcher: object | None = None
    settings: Settings | None = None

    def process_next_run(self, db: Session, *, worker_id: str | None = None) -> str | None:
        resolved_worker_id = worker_id or f"{socket.gethostname()}-worker"
        settings = self.settings or Settings(database_url="sqlite://")
        agent_profile_service = self.agent_profile_service or AgentProfileService(
            repository=AgentRepository(),
            settings=settings,
        )
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
            emit_event(
                logger,
                event=build_event(
                    settings=settings,
                    event_name="execution_run.claimed",
                    component="worker",
                    status="claimed",
                    trace_id=run.trace_id,
                    session_id=run.session_id,
                    execution_run_id=run.id,
                    message_id=run.message_id,
                    agent_id=run.agent_id,
                ),
            )
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
            message = self.session_repository.get_message(db, message_id=run.message_id) if run.message_id else None
            if message is None:
                raise RuntimeError("missing canonical transcript state for execution run")
            session = self.session_repository.get_session(db, run.session_id)
            if session is None:
                raise RuntimeError("session not found for execution run")
            if run.agent_id != session.owner_agent_id:
                raise RuntimeError("execution run agent_id does not match session owner")
            binding = agent_profile_service.resolve_binding_for_run(db, run=run, session=session)
            try:
                graph = self.assistant_graph_factory(binding)
            except TypeError:
                graph = self.assistant_graph_factory()  # pragma: no cover - compatibility for older test doubles
            if run.trigger_kind == "inbound_message" and self.media_processor is not None:
                self.media_processor.normalize_message_attachments(
                    db=db,
                    repository=self.session_repository,
                    session_id=run.session_id,
                    message_id=message.id,
                )
                self._run_same_turn_attachment_fast_path(db=db, message_id=message.id)
            state = graph.invoke(
                db=db,
                session_id=run.session_id,
                message_id=message.id,
                agent_id=run.agent_id,
                channel_kind=self.session_repository.get_session_channel_kind(db, session_id=run.session_id),
                sender_id=message.sender_id,
                user_text=message.content,
                execution_binding=binding,
                execution_run_id=run.id,
                persist_final_message=False,
            )
            if self.outbound_dispatcher is not None:
                self.outbound_dispatcher.dispatch_run(
                    db=db,
                    repository=self.session_repository,
                    session=session,
                    execution_run_id=run.id,
                    assistant_text=state.response_text,
                )
            graph.persist_final_state(db=db, state=state)
            self._enqueue_after_turn_jobs(
                db,
                session_id=run.session_id,
                message_id=message.id,
                summary_message_id=state.assistant_message_id,
                degraded=state.degraded,
                trace_id=run.trace_id,
            )
            self.jobs_repository.complete_run(db, run_id=run.id, worker_id=resolved_worker_id)
            emit_event(
                logger,
                event=build_event(
                    settings=settings,
                    event_name="execution_run.completed",
                    component="worker",
                    status="completed",
                    trace_id=run.trace_id,
                    session_id=run.session_id,
                    execution_run_id=run.id,
                    message_id=run.message_id,
                    agent_id=run.agent_id,
                ),
            )
            if run.trigger_kind == "scheduler_fire":
                self.jobs_repository.mark_fire_by_key(db, fire_key=run.trigger_ref, status="completed")
            return run.id
        except Exception as exc:
            decision = self.failure_classifier.classify(exc)
            run.failure_category = classify_failure(exc=exc)
            if decision.retryable:
                updated_run = self.jobs_repository.retry_run(
                    db,
                    run_id=run.id,
                    worker_id=resolved_worker_id,
                    error=decision.reason,
                    backoff_seconds=self._backoff_seconds(run.attempt_count),
                )
                updated_run.failure_category = classify_failure(exc=exc)
                if run.trigger_kind == "scheduler_fire" and updated_run.status == "dead_letter":
                    self.jobs_repository.mark_fire_by_key(
                        db,
                        fire_key=run.trigger_ref,
                        status="failed",
                        error=decision.reason,
                    )
            else:
                failed_run = self.jobs_repository.fail_run(
                    db,
                    run_id=run.id,
                    worker_id=resolved_worker_id,
                    error=decision.reason,
                )
                failed_run.failure_category = classify_failure(exc=exc)
                if run.trigger_kind == "scheduler_fire":
                    self.jobs_repository.mark_fire_by_key(
                        db,
                        fire_key=run.trigger_ref,
                        status="failed",
                        error=decision.reason,
                    )
            emit_event(
                logger,
                level=logging.ERROR,
                event=build_event(
                    settings=settings,
                    event_name="execution_run.failed",
                    component="worker",
                    status="failed",
                    trace_id=run.trace_id,
                    session_id=run.session_id,
                    execution_run_id=run.id,
                    message_id=run.message_id,
                    agent_id=run.agent_id,
                    error=str(exc),
                    failure_category=classify_failure(exc=exc),
                ),
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

    def _run_same_turn_attachment_fast_path(self, db: Session, *, message_id: int) -> None:
        if self.attachment_extraction_service is None:
            return
        settings = self.settings or Settings(database_url="sqlite://")
        if not settings.attachment_same_run_fast_path_enabled:
            return
        attachments = self.session_repository.list_stored_message_attachments_for_message(db, message_id=message_id)
        for attachment in attachments:
            if attachment.mime_type.startswith("image/"):
                continue
            if attachment.byte_size is not None and attachment.byte_size > settings.attachment_same_run_max_bytes:
                continue
            self.attachment_extraction_service.extract_attachment(
                db=db,
                repository=self.session_repository,
                attachment_id=attachment.id,
                extractor_kind="default",
                same_run=True,
            )

    def _backoff_seconds(self, attempt_count: int) -> int:
        return min(self.base_backoff_seconds * (2 ** max(attempt_count, 0)), self.max_backoff_seconds)

    def _enqueue_after_turn_jobs(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        summary_message_id: int | None,
        degraded: bool,
        trace_id: str | None = None,
    ) -> None:
        settings = self.settings or Settings(database_url="sqlite://")
        summary_target_message_id = summary_message_id or message_id
        self.session_repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=summary_target_message_id,
            job_kind="summary_generation",
            job_dedupe_key=f"summary_generation:{session_id}:{summary_target_message_id}",
            payload={
                "job_kind": "summary_generation",
                "source": {
                    "source_kind": "message",
                    "source_id": summary_target_message_id,
                    "strategy_id": "summary-v1",
                },
            },
            trace_id=trace_id,
        )
        self.session_repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="memory_extraction",
            job_dedupe_key=f"memory_extraction:message:{message_id}",
            payload={
                "job_kind": "memory_extraction",
                "source": {"source_kind": "message", "source_id": message_id, "strategy_id": settings.memory_strategy_id},
            },
            trace_id=trace_id,
        )
        self.session_repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="retrieval_index",
            job_dedupe_key=f"retrieval_index:message:{message_id}",
            payload={
                "job_kind": "retrieval_index",
                "source": {"source_kind": "message", "source_id": message_id, "strategy_id": settings.retrieval_strategy_id},
            },
            trace_id=trace_id,
        )
        for attachment in self.session_repository.list_stored_message_attachments_for_message(db, message_id=message_id):
            self.session_repository.enqueue_outbox_job(
                db,
                session_id=session_id,
                message_id=message_id,
                job_kind="attachment_extraction",
                job_dedupe_key=f"attachment_extraction:{attachment.id}:default",
                payload={
                    "job_kind": "attachment_extraction",
                    "message_id": message_id,
                    "source": {
                        "source_kind": "attachment",
                        "source_id": attachment.id,
                        "extractor_kind": "default",
                        "strategy_id": settings.attachment_extraction_strategy_id,
                    },
                },
                trace_id=trace_id,
            )
        if degraded:
            self.session_repository.enqueue_outbox_job(
                db,
                session_id=session_id,
                message_id=summary_target_message_id,
                job_kind="continuity_repair",
                job_dedupe_key=f"continuity_repair:{session_id}:{summary_target_message_id}",
                payload={
                    "job_kind": "continuity_repair",
                    "source": {
                        "source_kind": "message",
                        "source_id": summary_target_message_id,
                        "strategy_id": "continuity-v1",
                    },
                },
                trace_id=trace_id,
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
