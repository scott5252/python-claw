from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from sqlalchemy.orm import Session

from src.domain.schemas import (
    ExecutionRunResponse,
    MessagePageResponse,
    PendingApprovalResponse,
    SessionResponse,
    SessionRunPageResponse,
)
from src.jobs.repository import JobsRepository
from src.gateway.idempotency import (
    ClaimAccepted,
    DuplicateReplay,
    IdempotencyConflictError,
    IdempotencyKey,
    IdempotencyService,
)
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


@dataclass
class InboundProcessResult:
    session_id: str
    message_id: int
    run_id: str
    status: str
    dedupe_status: str


class SessionService:
    def __init__(
        self,
        *,
        repository: SessionRepository,
        jobs_repository: JobsRepository,
        idempotency_service: IdempotencyService,
        default_agent_id: str,
        dedupe_retention_days: int,
        dedupe_stale_after_seconds: int,
        messages_page_default_limit: int,
        messages_page_max_limit: int,
        session_runs_page_default_limit: int,
        session_runs_page_max_limit: int,
        execution_run_max_attempts: int,
    ):
        self.repository = repository
        self.jobs_repository = jobs_repository
        self.idempotency_service = idempotency_service
        self.default_agent_id = default_agent_id
        self.dedupe_retention_days = dedupe_retention_days
        self.dedupe_stale_after_seconds = dedupe_stale_after_seconds
        self.messages_page_default_limit = messages_page_default_limit
        self.messages_page_max_limit = messages_page_max_limit
        self.session_runs_page_default_limit = session_runs_page_default_limit
        self.session_runs_page_max_limit = session_runs_page_max_limit
        self.execution_run_max_attempts = execution_run_max_attempts

    def process_inbound(
        self,
        *,
        db: Session,
        channel_kind: str,
        channel_account_id: str,
        external_message_id: str,
        sender_id: str,
        content: str,
        peer_id: str | None,
        group_id: str | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> InboundProcessResult:
        routing = normalize_routing_input(
            RoutingInput(
                channel_kind=channel_kind,
                channel_account_id=channel_account_id,
                sender_id=sender_id,
                peer_id=peer_id,
                group_id=group_id,
            )
        )

        claim_result = self.idempotency_service.claim(
            db,
            key=IdempotencyKey(
                channel_kind=routing.channel_kind,
                channel_account_id=routing.channel_account_id,
                external_message_id=external_message_id.strip(),
            ),
            retention_days=self.dedupe_retention_days,
            stale_after_seconds=self.dedupe_stale_after_seconds,
        )

        if isinstance(claim_result, DuplicateReplay):
            run = self.jobs_repository.get_execution_run_by_trigger(
                db,
                trigger_kind="inbound_message",
                trigger_ref=str(claim_result.message_id),
            )
            if run is None:
                raise IdempotencyConflictError("dedupe replay is missing execution run")
            return InboundProcessResult(
                session_id=claim_result.session_id,
                message_id=claim_result.message_id,
                run_id=run.id,
                status=run.status,
                dedupe_status="duplicate",
            )
        if not isinstance(claim_result, ClaimAccepted):
            raise IdempotencyConflictError("dedupe claim is already in progress")

        now = datetime.now(timezone.utc)
        session = self.repository.get_or_create_session(db, routing)
        message = self.repository.append_message(
            db,
            session,
            role="user",
            content=content,
            external_message_id=external_message_id.strip(),
            sender_id=routing.sender_id,
            last_activity_at=now,
        )
        if attachments:
            self.repository.append_inbound_attachments(
                db,
                session_id=session.id,
                message_id=message.id,
                attachments=attachments,
            )
        run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=message.id,
            agent_id=self.default_agent_id,
            trigger_kind="inbound_message",
            trigger_ref=str(message.id),
            lane_key=session.id,
            max_attempts=self.execution_run_max_attempts,
            now=now,
        )
        self.idempotency_service.finalize(
            db,
            dedupe_id=claim_result.dedupe_id,
            session_id=session.id,
            message_id=message.id,
            expires_at=now + timedelta(days=self.dedupe_retention_days),
        )
        return InboundProcessResult(
            session_id=session.id,
            message_id=message.id,
            run_id=run.id,
            status=run.status,
            dedupe_status="accepted",
        )

    def submit_scheduler_fire(
        self,
        db: Session,
        *,
        scheduled_job,
        fire,
        payload: dict[str, object],
    ) -> tuple[str, str]:
        existing_run = self.jobs_repository.get_execution_run_by_trigger(
            db,
            trigger_kind="scheduler_fire",
            trigger_ref=fire.fire_key,
        )
        if existing_run is not None:
            return existing_run.id, existing_run.status
        session = self._resolve_scheduler_session(db, scheduled_job=scheduled_job)
        content = json.dumps(payload, sort_keys=True)
        message = self.repository.append_message(
            db,
            session,
            role="user",
            content=content,
            external_message_id=None,
            sender_id=f"scheduler:{scheduled_job.job_key}",
            last_activity_at=datetime.now(timezone.utc),
        )
        run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=message.id,
            agent_id=scheduled_job.agent_id,
            trigger_kind="scheduler_fire",
            trigger_ref=fire.fire_key,
            lane_key=session.id,
            max_attempts=self.execution_run_max_attempts,
        )
        return run.id, run.status

    def _resolve_scheduler_session(self, db: Session, *, scheduled_job):
        if scheduled_job.target_kind == "session":
            if scheduled_job.session_id is None:
                raise RuntimeError("scheduled session target not found")
            session = self.repository.get_session(db, scheduled_job.session_id)
            if session is None:
                raise RuntimeError("scheduled session target not found")
            return session

        if scheduled_job.target_kind != "routing_tuple":
            raise RuntimeError("scheduled job target_kind is unsupported")

        routing = normalize_routing_input(
            RoutingInput(
                channel_kind=scheduled_job.channel_kind or "",
                channel_account_id=scheduled_job.channel_account_id or "",
                sender_id=f"scheduler:{scheduled_job.job_key}",
                peer_id=scheduled_job.peer_id,
                group_id=scheduled_job.group_id,
            )
        )
        return self.repository.get_or_create_session(db, routing)

    def get_session(self, db: Session, session_id: str) -> SessionResponse | None:
        session = self.repository.get_session(db, session_id)
        if session is None:
            return None
        return SessionResponse.model_validate(session, from_attributes=True)

    def get_messages(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int | None,
        before_message_id: int | None,
    ) -> MessagePageResponse | None:
        session = self.repository.get_session(db, session_id)
        if session is None:
            return None
        page_limit = min(limit or self.messages_page_default_limit, self.messages_page_max_limit)
        rows = self.repository.list_messages(
            db,
            session_id=session_id,
            limit=page_limit,
            before_message_id=before_message_id,
        )
        next_before = rows[0].id if len(rows) == page_limit else None
        return MessagePageResponse(
            items=[
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "role": row.role,
                    "content": row.content,
                    "external_message_id": row.external_message_id,
                    "sender_id": row.sender_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
            next_before_message_id=next_before,
        )

    def get_pending_approvals(self, db: Session, *, session_id: str) -> list[PendingApprovalResponse] | None:
        session = self.repository.get_session(db, session_id)
        if session is None:
            return None
        return [
            PendingApprovalResponse.model_validate(item)
            for item in self.repository.list_pending_approvals(db, session_id=session_id)
        ]

    def get_run(self, db: Session, run_id: str) -> ExecutionRunResponse | None:
        run = self.jobs_repository.get_execution_run(db, run_id)
        if run is None:
            return None
        return ExecutionRunResponse.model_validate(run, from_attributes=True)

    def get_session_runs(
        self,
        db: Session,
        *,
        session_id: str,
        limit: int | None,
    ) -> SessionRunPageResponse | None:
        session = self.repository.get_session(db, session_id)
        if session is None:
            return None
        page_limit = min(limit or self.session_runs_page_default_limit, self.session_runs_page_max_limit)
        runs = self.jobs_repository.list_session_runs(db, session_id=session_id, limit=page_limit)
        return SessionRunPageResponse(
            items=[ExecutionRunResponse.model_validate(run, from_attributes=True) for run in runs]
        )
