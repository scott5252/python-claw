from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import SessionAutomationState, SessionKind
from src.jobs.repository import JobsRepository
from src.sessions.repository import SessionRepository


@dataclass
class CollaborationConflictError(RuntimeError):
    message: str = "stale collaboration version"


@dataclass
class SessionCollaborationService:
    repository: SessionRepository
    jobs_repository: JobsRepository
    settings: Settings

    def _require_primary_session(self, session) -> None:
        if session.session_kind != SessionKind.PRIMARY.value:
            raise ValueError("collaboration controls only apply to primary sessions")

    def _apply_state_change(
        self,
        db: Session,
        *,
        session_id: str,
        expected_collaboration_version: int,
        operator_id: str,
        target_state: str,
        reason: str | None,
        event_kind: str,
        note: str | None = None,
    ):
        session = self.repository.get_session_for_update(db, session_id=session_id)
        if session is None:
            raise LookupError("session not found")
        self._require_primary_session(session)
        before_state = session.automation_state
        before_operator = session.assigned_operator_id
        before_queue = session.assigned_queue_key
        try:
            self.repository.update_session_collaboration(
                db,
                session=session,
                expected_collaboration_version=expected_collaboration_version,
                automation_state=target_state,
                reason=reason,
            )
        except ValueError as exc:
            raise CollaborationConflictError() from exc
        note_row = None
        if note:
            note_row = self.repository.append_operator_note(
                db,
                session_id=session.id,
                author_kind="operator",
                author_id=operator_id,
                note_kind="internal",
                body=note,
            )
        self.repository.append_collaboration_event(
            db,
            session_id=session.id,
            event_kind=event_kind,
            actor_kind="operator",
            actor_id=operator_id,
            automation_state_before=before_state,
            automation_state_after=session.automation_state,
            assigned_operator_before=before_operator,
            assigned_operator_after=session.assigned_operator_id,
            assigned_queue_before=before_queue,
            assigned_queue_after=session.assigned_queue_key,
            related_note_id=None if note_row is None else note_row.id,
            payload={"reason": reason} if reason else {},
        )
        if target_state == SessionAutomationState.ASSISTANT_ACTIVE.value:
            self.jobs_repository.release_blocked_runs(db, session_id=session.id)
        return session

    def takeover_session(
        self,
        db: Session,
        *,
        session_id: str,
        expected_collaboration_version: int,
        operator_id: str,
        reason: str | None = None,
        note: str | None = None,
    ):
        return self._apply_state_change(
            db,
            session_id=session_id,
            expected_collaboration_version=expected_collaboration_version,
            operator_id=operator_id,
            target_state=SessionAutomationState.HUMAN_TAKEOVER.value,
            reason=reason,
            event_kind="takeover",
            note=note,
        )

    def pause_session(
        self,
        db: Session,
        *,
        session_id: str,
        expected_collaboration_version: int,
        operator_id: str,
        reason: str | None = None,
        note: str | None = None,
    ):
        return self._apply_state_change(
            db,
            session_id=session_id,
            expected_collaboration_version=expected_collaboration_version,
            operator_id=operator_id,
            target_state=SessionAutomationState.PAUSED.value,
            reason=reason,
            event_kind="pause",
            note=note,
        )

    def resume_session(
        self,
        db: Session,
        *,
        session_id: str,
        expected_collaboration_version: int,
        operator_id: str,
        reason: str | None = None,
        note: str | None = None,
    ):
        return self._apply_state_change(
            db,
            session_id=session_id,
            expected_collaboration_version=expected_collaboration_version,
            operator_id=operator_id,
            target_state=SessionAutomationState.ASSISTANT_ACTIVE.value,
            reason=reason,
            event_kind="resume",
            note=note,
        )

    def assign_session(
        self,
        db: Session,
        *,
        session_id: str,
        expected_collaboration_version: int,
        operator_id: str,
        assigned_operator_id: str | None,
        assigned_queue_key: str | None,
        reason: str | None = None,
        note: str | None = None,
    ):
        session = self.repository.get_session_for_update(db, session_id=session_id)
        if session is None:
            raise LookupError("session not found")
        self._require_primary_session(session)
        before_state = session.automation_state
        before_operator = session.assigned_operator_id
        before_queue = session.assigned_queue_key
        try:
            self.repository.update_session_collaboration(
                db,
                session=session,
                expected_collaboration_version=expected_collaboration_version,
                assigned_operator_id=assigned_operator_id,
                assigned_queue_key=assigned_queue_key or self.settings.default_assignment_queue_key,
                reason=reason,
                update_assignment=True,
            )
        except ValueError as exc:
            raise CollaborationConflictError() from exc
        note_row = None
        if note:
            note_row = self.repository.append_operator_note(
                db,
                session_id=session.id,
                author_kind="operator",
                author_id=operator_id,
                note_kind="internal",
                body=note,
            )
        self.repository.append_collaboration_event(
            db,
            session_id=session.id,
            event_kind="assignment_changed",
            actor_kind="operator",
            actor_id=operator_id,
            automation_state_before=before_state,
            automation_state_after=session.automation_state,
            assigned_operator_before=before_operator,
            assigned_operator_after=session.assigned_operator_id,
            assigned_queue_before=before_queue,
            assigned_queue_after=session.assigned_queue_key,
            related_note_id=None if note_row is None else note_row.id,
            payload={"reason": reason} if reason else {},
        )
        return session

    def add_operator_note(
        self,
        db: Session,
        *,
        session_id: str,
        operator_id: str,
        note_kind: str,
        body: str,
    ):
        session = self.repository.get_session(db, session_id)
        if session is None:
            raise LookupError("session not found")
        self._require_primary_session(session)
        note = self.repository.append_operator_note(
            db,
            session_id=session_id,
            author_kind="operator",
            author_id=operator_id,
            note_kind=note_kind,
            body=body,
        )
        self.repository.append_collaboration_event(
            db,
            session_id=session_id,
            event_kind="note_created",
            actor_kind="operator",
            actor_id=operator_id,
            automation_state_before=session.automation_state,
            automation_state_after=session.automation_state,
            assigned_operator_before=session.assigned_operator_id,
            assigned_operator_after=session.assigned_operator_id,
            assigned_queue_before=session.assigned_queue_key,
            assigned_queue_after=session.assigned_queue_key,
            related_note_id=note.id,
            payload={"note_kind": note_kind},
        )
        return note

    def should_block_new_automation(self, *, session) -> bool:
        if session.session_kind != SessionKind.PRIMARY.value:
            return False
        return session.automation_state != SessionAutomationState.ASSISTANT_ACTIVE.value

    def blocked_reason_for_session(self, *, session) -> str | None:
        if not self.should_block_new_automation(session=session):
            return None
        return f"automation_state:{session.automation_state}"

    def build_collaboration_snapshot(self, db: Session, *, session_id: str) -> dict[str, object]:
        session = self.repository.get_session(db, session_id)
        if session is None:
            raise LookupError("session not found")
        return {
            "session_id": session.id,
            "automation_state": session.automation_state,
            "assigned_operator_id": session.assigned_operator_id,
            "assigned_queue_key": session.assigned_queue_key,
            "automation_state_reason": session.automation_state_reason,
            "automation_state_changed_at": session.automation_state_changed_at,
            "assignment_updated_at": session.assignment_updated_at,
            "collaboration_version": session.collaboration_version,
            "blocked_run_count": self.repository.count_blocked_runs(db, session_id=session.id),
        }

    def record_suppressed_run(
        self,
        db: Session,
        *,
        session_id: str,
        run_id: str,
        actor_id: str | None = None,
        reason: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.repository.append_collaboration_event(
            db,
            session_id=session_id,
            event_kind="dispatch_suppressed",
            actor_kind="system",
            actor_id=actor_id,
            related_run_id=run_id,
            payload={"reason": reason, **(payload or {})},
        )
