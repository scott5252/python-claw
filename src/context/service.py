from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.graphs.state import AssistantState, ConversationMessage
from src.observability.logging import build_event, emit_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextAssemblyResult:
    messages: list[ConversationMessage]
    manifest: dict[str, Any]
    degraded: bool = False


@dataclass
class ContextService:
    context_window: int
    settings: Settings | None = None

    def assemble(
        self,
        *,
        db: Session,
        repository: Any,
        session_id: str,
        message_id: int,
        agent_id: str,
        channel_kind: str,
        sender_id: str,
        user_text: str,
    ) -> AssistantState:
        transcript_rows = repository.list_messages(
            db,
            session_id=session_id,
            limit=max(message_id, self.context_window * 10),
            before_message_id=None,
        )
        transcript_rows = [row for row in transcript_rows if row.id <= message_id]
        transcript_messages = [
            ConversationMessage(role=row.role, content=row.content, sender_id=row.sender_id)
            for row in transcript_rows
        ]
        artifacts = repository.list_artifacts(db, session_id=session_id)
        governance_events = repository.list_governance_events(db, session_id=session_id)
        attachments = repository.list_stored_message_attachments_for_message(db, message_id=message_id)
        summary = repository.get_latest_valid_summary_snapshot(
            db,
            session_id=session_id,
            message_id=message_id,
        )

        initial_manifest = self._build_manifest(
            assembly_mode="transcript_full",
            session_id=session_id,
            message_id=message_id,
            transcript_rows=transcript_rows,
            selected_rows=transcript_rows,
            summary=summary,
            artifacts=artifacts,
            governance_events=governance_events,
            attachments=attachments,
            overflow=None,
            degraded=False,
        )

        if len(transcript_messages) <= self.context_window:
            self._emit_manifest(initial_manifest)
            return AssistantState(
                session_id=session_id,
                message_id=message_id,
                agent_id=agent_id,
                channel_kind=channel_kind,
                sender_id=sender_id,
                user_text=user_text,
                messages=transcript_messages,
                context_manifest=initial_manifest,
            )

        retry_rows: list[Any]
        retry_messages: list[ConversationMessage]
        assembly_mode = "compacted_retry"
        degraded = False
        if summary is not None:
            retry_rows = [row for row in transcript_rows if row.id > summary.through_message_id]
            tail_limit = max(self.context_window - 1, 0)
            retry_rows = retry_rows[-tail_limit:] if tail_limit > 0 else []
            retry_messages = [
                ConversationMessage(role="assistant", content=f"[summary] {summary.summary_text}", sender_id=agent_id),
                *[
                    ConversationMessage(role=row.role, content=row.content, sender_id=row.sender_id)
                    for row in retry_rows
                ],
            ]
        else:
            retry_rows = []
            retry_messages = []

        if len(retry_messages) > self.context_window or not retry_messages:
            degraded = True
            assembly_mode = "degraded_failure"
            retry_rows = transcript_rows[-1:]
            retry_messages = [
                ConversationMessage(role=row.role, content=row.content, sender_id=row.sender_id)
                for row in retry_rows
            ]

        retry_manifest = self._build_manifest(
            assembly_mode=assembly_mode,
            session_id=session_id,
            message_id=message_id,
            transcript_rows=transcript_rows,
            selected_rows=retry_rows,
            summary=summary,
            artifacts=artifacts,
            governance_events=governance_events,
            attachments=attachments,
            overflow={
                "status": "retry",
                "initial_transcript_count": len(transcript_messages),
                "context_window": self.context_window,
            },
            degraded=degraded,
        )
        self._emit_manifest(retry_manifest)
        return AssistantState(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            channel_kind=channel_kind,
            sender_id=sender_id,
            user_text=user_text,
            messages=retry_messages,
            context_manifest=retry_manifest,
            degraded=degraded,
        )

    def persist_manifest(
        self,
        *,
        db: Session,
        repository: Any,
        state: AssistantState,
    ) -> None:
        repository.append_context_manifest(
            db,
            session_id=state.session_id,
            message_id=state.message_id,
            manifest=state.context_manifest,
            degraded=state.degraded,
        )

    def _build_manifest(
        self,
        *,
        assembly_mode: str,
        session_id: str,
        message_id: int,
        transcript_rows: list[Any],
        selected_rows: list[Any],
        summary: Any | None,
        artifacts: list[Any],
        governance_events: list[Any],
        attachments: list[Any],
        overflow: dict[str, Any] | None,
        degraded: bool,
    ) -> dict[str, Any]:
        transcript_range: dict[str, int] | None = None
        if selected_rows:
            transcript_range = {
                "from_message_id": selected_rows[0].id,
                "through_message_id": selected_rows[-1].id,
            }
        full_transcript_range: dict[str, int] | None = None
        if transcript_rows:
            full_transcript_range = {
                "from_message_id": transcript_rows[0].id,
                "through_message_id": transcript_rows[-1].id,
            }
        return {
            "session_id": session_id,
            "message_id": message_id,
            "assembly_mode": assembly_mode,
            "degraded": degraded,
            "transcript_range": transcript_range,
            "full_transcript_range": full_transcript_range,
            "summary_snapshot_ids": [] if summary is None else [summary.id],
            "summary_range": None
            if summary is None
            else {
                "base_message_id": summary.base_message_id,
                "through_message_id": summary.through_message_id,
                "source_watermark_message_id": summary.source_watermark_message_id,
            },
            "retrieval_ids": [],
            "assistant_tool_artifact_ids": [artifact.id for artifact in artifacts],
            "governance_artifact_ids": [event.id for event in governance_events],
            "attachment_ids": [attachment.id for attachment in attachments],
            "attachments": [
                {
                    "id": attachment.id,
                    "media_kind": attachment.media_kind,
                    "mime_type": attachment.mime_type,
                    "storage_key": attachment.storage_key,
                    "filename": attachment.filename,
                }
                for attachment in attachments
            ],
            "overflow": overflow,
        }

    def _emit_manifest(self, manifest: dict[str, Any]) -> None:
        if self.settings is None:
            logger.info("context manifest generated", extra={"context_manifest": json.dumps(manifest, sort_keys=True)})
            return
        emit_event(
            logger,
            event=build_event(
                settings=self.settings,
                event_name="context.manifest.generated",
                component="context",
                status="degraded" if manifest.get("degraded") else "ok",
                trace_id=None,
                session_id=manifest.get("session_id"),
                message_id=manifest.get("message_id"),
                degraded=manifest.get("degraded"),
                assembly_mode=manifest.get("assembly_mode"),
                attachment_ids=manifest.get("attachment_ids"),
            ),
        )
