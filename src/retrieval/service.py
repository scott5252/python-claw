from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RetrievalCandidate:
    record: Any
    score: float
    ranking_metadata: dict[str, Any]


@dataclass
class RetrievalService:
    strategy_id: str
    chunk_chars: int
    min_score: float

    def index_message(self, *, db: Session, repository: Any, message_id: int) -> list[Any]:
        message = repository.get_message(db, message_id=message_id)
        if message is None or not self._eligible(message.content):
            return []
        return self._index_chunks(
            db=db,
            repository=repository,
            session_id=message.session_id,
            source_kind="message",
            source_id=message.id,
            source_message_id=message.id,
            text=message.content,
        )

    def index_summary(self, *, db: Session, repository: Any, summary_snapshot_id: int) -> list[Any]:
        summary = repository.get_summary_snapshot(db, summary_snapshot_id=summary_snapshot_id)
        if summary is None or not self._eligible(summary.summary_text):
            return []
        return self._index_chunks(
            db=db,
            repository=repository,
            session_id=summary.session_id,
            source_kind="summary_snapshot",
            source_id=summary.id,
            source_summary_snapshot_id=summary.id,
            text=summary.summary_text,
        )

    def index_memory(self, *, db: Session, repository: Any, memory_id: int) -> list[Any]:
        memory = repository.get_session_memory(db, memory_id=memory_id)
        if memory is None or memory.status != "active" or not self._eligible(memory.content_text):
            return []
        return self._index_chunks(
            db=db,
            repository=repository,
            session_id=memory.session_id,
            source_kind="memory",
            source_id=memory.id,
            source_memory_id=memory.id,
            text=memory.content_text,
        )

    def index_attachment_extraction(self, *, db: Session, repository: Any, attachment_extraction_id: int) -> list[Any]:
        extraction = repository.get_attachment_extraction_by_id(db, attachment_extraction_id=attachment_extraction_id)
        if extraction is None or extraction.status != "completed" or not self._eligible(extraction.content_text or ""):
            return []
        return self._index_chunks(
            db=db,
            repository=repository,
            session_id=extraction.session_id,
            source_kind="attachment_extraction",
            source_id=extraction.id,
            source_attachment_extraction_id=extraction.id,
            text=extraction.content_text or "",
        )

    def retrieve(
        self,
        *,
        db: Session,
        repository: Any,
        session_id: str,
        query_text: str,
        limit: int,
    ) -> list[RetrievalCandidate]:
        terms = self._terms(query_text)
        if not terms or limit <= 0:
            return []
        candidates: list[RetrievalCandidate] = []
        for record in repository.list_retrieval_records(db, session_id=session_id):
            record_terms = self._terms(record.content_text)
            overlap = len(terms.intersection(record_terms))
            if overlap < self.min_score:
                continue
            ranking_metadata = json.loads(record.ranking_metadata_json or "{}")
            candidates.append(
                RetrievalCandidate(
                    record=record,
                    score=float(overlap),
                    ranking_metadata={**ranking_metadata, "overlap_terms": sorted(terms.intersection(record_terms))},
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.record.id))
        return candidates[:limit]

    def _index_chunks(
        self,
        *,
        db: Session,
        repository: Any,
        session_id: str,
        source_kind: str,
        source_id: int,
        text: str,
        source_message_id: int | None = None,
        source_summary_snapshot_id: int | None = None,
        source_memory_id: int | None = None,
        source_attachment_extraction_id: int | None = None,
    ) -> list[Any]:
        created: list[Any] = []
        for index, chunk in enumerate(self._chunk_text(text)):
            created.append(
                repository.create_or_get_retrieval_record(
                    db,
                    session_id=session_id,
                    source_kind=source_kind,
                    source_id=source_id,
                    source_message_id=source_message_id,
                    source_summary_snapshot_id=source_summary_snapshot_id,
                    source_memory_id=source_memory_id,
                    source_attachment_extraction_id=source_attachment_extraction_id,
                    chunk_index=index,
                    content_text=chunk,
                    content_hash=hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                    ranking_metadata={"length": len(chunk)},
                    derivation_strategy_id=self.strategy_id,
                )
            )
        return created

    def _chunk_text(self, text: str) -> list[str]:
        cleaned = " ".join(text.split())
        if not cleaned:
            return []
        return [cleaned[index : index + self.chunk_chars] for index in range(0, len(cleaned), self.chunk_chars)]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {item for item in re.findall(r"[a-z0-9]+", text.lower()) if len(item) >= 3}

    def _eligible(self, text: str) -> bool:
        return bool(text and text.strip())
