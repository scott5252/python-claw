from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.graphs.state import (
    AssemblyMetadata,
    AssistantState,
    AttachmentContextItem,
    AttachmentFallbackItem,
    ConversationMessage,
    MemoryContextItem,
    RetrievalContextItem,
    SummaryContext,
)
from src.observability.logging import build_event, emit_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextAssemblyResult:
    messages: list[ConversationMessage]
    manifest: dict[str, Any]
    summary_context: SummaryContext | None
    memory_items: list[MemoryContextItem]
    retrieval_items: list[RetrievalContextItem]
    attachment_items: list[AttachmentContextItem]
    attachment_fallbacks: list[AttachmentFallbackItem]
    assembly_metadata: AssemblyMetadata
    degraded: bool = False


@dataclass
class ContextService:
    context_window: int
    settings: Settings | None = None
    retrieval_service: Any | None = None

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
        settings = self.settings or Settings(database_url="sqlite://")
        transcript_rows = repository.list_messages(
            db,
            session_id=session_id,
            limit=max(message_id, self.context_window * 10),
            before_message_id=None,
        )
        transcript_rows = [row for row in transcript_rows if row.id <= message_id]
        summary = repository.get_latest_valid_summary_snapshot(db, session_id=session_id, message_id=message_id)
        attachments = repository.list_stored_message_attachments_for_message(db, message_id=message_id)

        selected_rows = transcript_rows[-self.context_window :]
        summary_context: SummaryContext | None = None
        assembly_mode = "transcript_recent"
        if len(transcript_rows) > self.context_window and summary is not None:
            tail_after_summary = [row for row in transcript_rows if row.id > summary.through_message_id]
            tail_limit = max(self.context_window - 1, 0)
            selected_rows = tail_after_summary[-tail_limit:] if tail_limit > 0 else []
            summary_context = SummaryContext(
                snapshot_id=summary.id,
                summary_text=summary.summary_text,
                base_message_id=summary.base_message_id,
                through_message_id=summary.through_message_id,
            )
            assembly_mode = "summary_plus_recent"
        elif len(transcript_rows) > self.context_window:
            selected_rows = transcript_rows[-1:]
            assembly_mode = "degraded_failure"

        transcript_messages = [
            ConversationMessage(role=row.role, content=row.content, sender_id=row.sender_id) for row in selected_rows
        ]
        degraded_reasons: list[str] = []
        if len(transcript_rows) > self.context_window and summary_context is None:
            degraded_reasons.append("continuity_overflow_no_summary")
        if not transcript_messages and summary_context is None and transcript_rows:
            transcript_messages = [
                ConversationMessage(
                    role=transcript_rows[-1].role,
                    content=transcript_rows[-1].content,
                    sender_id=transcript_rows[-1].sender_id,
                )
            ]
            degraded_reasons.append("transcript_only_recovery")
            assembly_mode = "degraded_transcript_only"

        memory_items: list[MemoryContextItem] = []
        retrieval_items: list[RetrievalContextItem] = []
        skipped_candidates: list[dict[str, Any]] = []
        if settings.retrieval_enabled and self.retrieval_service is not None:
            query_text = " ".join(
                [user_text, *[row.content for row in selected_rows[-3:]]]
            ).strip()
            candidate_limit = max(settings.retrieval_total_items * 3, settings.retrieval_total_items)
            try:
                for candidate in self.retrieval_service.retrieve(
                    db=db,
                    repository=repository,
                    session_id=session_id,
                    query_text=query_text,
                    limit=candidate_limit,
                ):
                    if self._covered_by_transcript(candidate=candidate.record, transcript_rows=selected_rows):
                        skipped_candidates.append(
                            {"retrieval_id": candidate.record.id, "reason": "covered_by_transcript"}
                        )
                        continue
                    if self._covered_by_summary(candidate=candidate.record, summary=summary_context):
                        skipped_candidates.append({"retrieval_id": candidate.record.id, "reason": "covered_by_summary"})
                        continue
                    if candidate.record.source_kind == "memory" and len(memory_items) < settings.retrieval_memory_items:
                        memory = repository.get_session_memory(db, memory_id=candidate.record.source_memory_id)
                        if memory is not None and memory.status == "active":
                            memory_items.append(
                                MemoryContextItem(
                                    memory_id=memory.id,
                                    memory_kind=memory.memory_kind,
                                    content_text=memory.content_text,
                                    source_kind=memory.source_kind,
                                    confidence=memory.confidence,
                                )
                            )
                        continue
                    if len(retrieval_items) >= settings.retrieval_total_items:
                        skipped_candidates.append({"retrieval_id": candidate.record.id, "reason": "budget"})
                        continue
                    retrieval_items.append(
                        RetrievalContextItem(
                            retrieval_id=candidate.record.id,
                            source_kind=candidate.record.source_kind,
                            source_id=candidate.record.source_id,
                            content_text=candidate.record.content_text,
                            score=candidate.score,
                            ranking_metadata=candidate.ranking_metadata,
                        )
                    )
            except Exception:
                degraded_reasons.append("retrieval_unavailable")

        attachment_items, attachment_fallbacks = self._assemble_attachment_context(
            db=db,
            repository=repository,
            attachments=attachments,
            settings=settings,
        )
        assembly_metadata = AssemblyMetadata(
            assembly_mode=assembly_mode,
            transcript_budget=self.context_window,
            retrieved_budget=settings.retrieval_total_items,
            retrieval_strategy=settings.retrieval_strategy_id,
            trimmed=len(transcript_rows) > len(selected_rows),
            degraded_reasons=degraded_reasons,
            skipped_candidates=skipped_candidates,
        )
        manifest = self._build_manifest(
            session_id=session_id,
            message_id=message_id,
            transcript_rows=transcript_rows,
            selected_rows=selected_rows,
            summary_context=summary_context,
            attachments=attachments,
            memory_items=memory_items,
            retrieval_items=retrieval_items,
            attachment_items=attachment_items,
            attachment_fallbacks=attachment_fallbacks,
            assembly_metadata=assembly_metadata,
            degraded=bool(degraded_reasons),
        )
        self._emit_manifest(manifest)
        return AssistantState(
            session_id=session_id,
            message_id=message_id,
            agent_id=agent_id,
            channel_kind=channel_kind,
            sender_id=sender_id,
            user_text=user_text,
            messages=transcript_messages,
            summary_context=summary_context,
            memory_items=memory_items,
            retrieval_items=retrieval_items,
            attachment_items=attachment_items,
            attachment_fallbacks=attachment_fallbacks,
            assembly_metadata=assembly_metadata,
            context_manifest=manifest,
            degraded=bool(degraded_reasons),
        )

    def persist_manifest(self, *, db: Session, repository: Any, state: AssistantState) -> None:
        repository.append_context_manifest(
            db,
            session_id=state.session_id,
            message_id=state.message_id,
            manifest=state.context_manifest,
            degraded=state.degraded,
        )

    def _assemble_attachment_context(
        self,
        *,
        db: Session,
        repository: Any,
        attachments: list[Any],
        settings: Settings,
    ) -> tuple[list[AttachmentContextItem], list[AttachmentFallbackItem]]:
        extraction_rows = repository.list_attachment_extractions_for_attachments(
            db,
            attachment_ids=[attachment.id for attachment in attachments],
        )
        latest_by_attachment: dict[int, Any] = {}
        for row in extraction_rows:
            latest_by_attachment.setdefault(row.attachment_id, row)
        attachment_items: list[AttachmentContextItem] = []
        attachment_fallbacks: list[AttachmentFallbackItem] = []
        for attachment in attachments:
            extraction = latest_by_attachment.get(attachment.id)
            if extraction is not None and extraction.status == "completed" and extraction.content_text:
                if len(attachment_items) < settings.retrieval_attachment_items:
                    attachment_items.append(
                        AttachmentContextItem(
                            attachment_id=attachment.id,
                            extraction_id=extraction.id,
                            filename=attachment.filename,
                            mime_type=attachment.mime_type,
                            content_text=extraction.content_text,
                            metadata=json.loads(extraction.content_metadata_json or "{}"),
                        )
                    )
                    continue
            attachment_fallbacks.append(
                AttachmentFallbackItem(
                    attachment_id=attachment.id,
                    filename=attachment.filename,
                    mime_type=attachment.mime_type,
                    storage_key=attachment.storage_key,
                    status="metadata_only" if extraction is None else extraction.status,
                    reason=None if extraction is None else extraction.error_detail,
                )
            )
        return attachment_items, attachment_fallbacks

    @staticmethod
    def _covered_by_transcript(*, candidate: Any, transcript_rows: list[Any]) -> bool:
        transcript_ids = {row.id for row in transcript_rows}
        return bool(candidate.source_message_id is not None and candidate.source_message_id in transcript_ids)

    @staticmethod
    def _covered_by_summary(*, candidate: Any, summary: SummaryContext | None) -> bool:
        if summary is None or candidate.source_message_id is None:
            return False
        return summary.base_message_id <= candidate.source_message_id <= summary.through_message_id

    def _build_manifest(
        self,
        *,
        session_id: str,
        message_id: int,
        transcript_rows: list[Any],
        selected_rows: list[Any],
        summary_context: SummaryContext | None,
        attachments: list[Any],
        memory_items: list[MemoryContextItem],
        retrieval_items: list[RetrievalContextItem],
        attachment_items: list[AttachmentContextItem],
        attachment_fallbacks: list[AttachmentFallbackItem],
        assembly_metadata: AssemblyMetadata,
        degraded: bool,
    ) -> dict[str, Any]:
        transcript_range = None
        if selected_rows:
            transcript_range = {
                "from_message_id": selected_rows[0].id,
                "through_message_id": selected_rows[-1].id,
            }
        full_transcript_range = None
        if transcript_rows:
            full_transcript_range = {
                "from_message_id": transcript_rows[0].id,
                "through_message_id": transcript_rows[-1].id,
            }
        return {
            "session_id": session_id,
            "message_id": message_id,
            "assembly_mode": assembly_metadata.assembly_mode,
            "degraded": degraded,
            "degraded_reasons": assembly_metadata.degraded_reasons,
            "transcript_range": transcript_range,
            "full_transcript_range": full_transcript_range,
            "summary_snapshot_ids": [] if summary_context is None else [summary_context.snapshot_id],
            "summary_range": None
            if summary_context is None
            else {
                "base_message_id": summary_context.base_message_id,
                "through_message_id": summary_context.through_message_id,
            },
            "memory_ids": [item.memory_id for item in memory_items],
            "retrieval_ids": [item.retrieval_id for item in retrieval_items],
            "attachment_ids": [attachment.id for attachment in attachments],
            "attachment_extraction_ids": [item.extraction_id for item in attachment_items],
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
            "attachment_fallbacks": [
                {
                    "attachment_id": item.attachment_id,
                    "status": item.status,
                    "reason": item.reason,
                }
                for item in attachment_fallbacks
            ],
            "retrieval_strategy": assembly_metadata.retrieval_strategy,
            "assembly_budget": {
                "transcript_budget": assembly_metadata.transcript_budget,
                "retrieved_budget": assembly_metadata.retrieved_budget,
            },
            "trimmed": assembly_metadata.trimmed,
            "skipped_candidates": assembly_metadata.skipped_candidates,
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
