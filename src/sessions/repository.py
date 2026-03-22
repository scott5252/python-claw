from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import MessageRecord, SessionRecord
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
