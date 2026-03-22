from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import MessageRecord, SessionArtifactRecord, SessionRecord
from src.graphs.state import ConversationMessage, ToolEvent, ToolRequest
from src.routing.service import RoutingResult


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
        rows = list(
            db.scalars(stmt.order_by(MessageRecord.id.desc()).limit(limit))
        )
        rows.reverse()
        return rows

    def list_artifacts(self, db: Session, *, session_id: str) -> list[SessionArtifactRecord]:
        stmt = (
            select(SessionArtifactRecord)
            .where(SessionArtifactRecord.session_id == session_id)
            .order_by(SessionArtifactRecord.id.asc())
        )
        return list(db.scalars(stmt))
