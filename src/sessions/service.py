from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.graphs.assistant_graph import AssistantGraph
from src.domain.schemas import MessagePageResponse, SessionResponse
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
    dedupe_status: str


class SessionService:
    def __init__(
        self,
        *,
        repository: SessionRepository,
        assistant_graph: AssistantGraph,
        idempotency_service: IdempotencyService,
        default_agent_id: str,
        dedupe_retention_days: int,
        dedupe_stale_after_seconds: int,
        page_default_limit: int,
        page_max_limit: int,
    ):
        self.repository = repository
        self.assistant_graph = assistant_graph
        self.idempotency_service = idempotency_service
        self.default_agent_id = default_agent_id
        self.dedupe_retention_days = dedupe_retention_days
        self.dedupe_stale_after_seconds = dedupe_stale_after_seconds
        self.page_default_limit = page_default_limit
        self.page_max_limit = page_max_limit

    def process_inbound(
        self,
        *,
        claim_db: Session,
        work_db: Session,
        channel_kind: str,
        channel_account_id: str,
        external_message_id: str,
        sender_id: str,
        content: str,
        peer_id: str | None,
        group_id: str | None,
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
            claim_db,
            key=IdempotencyKey(
                channel_kind=routing.channel_kind,
                channel_account_id=routing.channel_account_id,
                external_message_id=external_message_id.strip(),
            ),
            retention_days=self.dedupe_retention_days,
            stale_after_seconds=self.dedupe_stale_after_seconds,
        )
        claim_db.commit()
        claim_db.close()

        if isinstance(claim_result, DuplicateReplay):
            return InboundProcessResult(
                session_id=claim_result.session_id,
                message_id=claim_result.message_id,
                dedupe_status="duplicate",
            )
        if not isinstance(claim_result, ClaimAccepted):
            raise IdempotencyConflictError("dedupe claim is already in progress")

        now = datetime.now(timezone.utc)
        session = self.repository.get_or_create_session(work_db, routing)
        message = self.repository.append_message(
            work_db,
            session,
            role="user",
            content=content,
            external_message_id=external_message_id.strip(),
            sender_id=routing.sender_id,
            last_activity_at=now,
        )
        self.idempotency_service.finalize(
            work_db,
            dedupe_id=claim_result.dedupe_id,
            session_id=session.id,
            message_id=message.id,
            expires_at=now + timedelta(days=self.dedupe_retention_days),
        )
        self.assistant_graph.invoke(
            db=work_db,
            session_id=session.id,
            agent_id=self.default_agent_id,
            channel_kind=routing.channel_kind,
            sender_id=routing.sender_id,
            user_text=content,
        )
        work_db.commit()
        return InboundProcessResult(session_id=session.id, message_id=message.id, dedupe_status="accepted")

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
        page_limit = min(limit or self.page_default_limit, self.page_max_limit)
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
