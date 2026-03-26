from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class MemoryService:
    strategy_id: str

    def extract_from_message(self, *, db: Session, repository: Any, message_id: int):
        message = repository.get_message(db, message_id=message_id)
        if message is None:
            raise RuntimeError("missing canonical transcript state for memory extraction")
        if not self._eligible_text(message.content):
            return repository.create_or_get_session_memory(
                db,
                session_id=message.session_id,
                memory_kind="message_fact",
                content_text=message.content.strip() or "(empty)",
                content_hash=self._hash_text(message.content),
                status="rejected",
                confidence=0.0,
                source_kind="message",
                source_message_id=message.id,
                source_summary_snapshot_id=None,
                source_base_message_id=message.id,
                source_through_message_id=message.id,
                derivation_strategy_id=self.strategy_id,
                payload={"reason": "ineligible_content"},
            )
        return repository.create_or_get_session_memory(
            db,
            session_id=message.session_id,
            memory_kind="message_fact",
            content_text=message.content.strip(),
            content_hash=self._hash_text(message.content),
            status="active",
            confidence=0.5,
            source_kind="message",
            source_message_id=message.id,
            source_summary_snapshot_id=None,
            source_base_message_id=message.id,
            source_through_message_id=message.id,
            derivation_strategy_id=self.strategy_id,
            payload={"role": message.role},
        )

    def extract_from_summary(self, *, db: Session, repository: Any, summary_snapshot_id: int):
        summary = repository.get_summary_snapshot(db, summary_snapshot_id=summary_snapshot_id)
        if summary is None:
            raise RuntimeError("summary snapshot not found for memory extraction")
        if not self._eligible_text(summary.summary_text):
            return None
        return repository.create_or_get_session_memory(
            db,
            session_id=summary.session_id,
            memory_kind="summary_fact",
            content_text=summary.summary_text.strip(),
            content_hash=self._hash_text(summary.summary_text),
            status="active",
            confidence=0.4,
            source_kind="summary_snapshot",
            source_message_id=None,
            source_summary_snapshot_id=summary.id,
            source_base_message_id=summary.base_message_id,
            source_through_message_id=summary.through_message_id,
            derivation_strategy_id=self.strategy_id,
            payload={"source_watermark_message_id": summary.source_watermark_message_id},
        )

    @staticmethod
    def _eligible_text(text: str) -> bool:
        stripped = text.strip()
        return len(stripped) >= 8 and not stripped.startswith("[summary]")

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
