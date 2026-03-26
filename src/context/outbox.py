from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class OutboxWorker:
    repository: Any
    memory_service: Any | None = None
    retrieval_service: Any | None = None
    attachment_extraction_service: Any | None = None

    def run_pending(
        self,
        db: Session,
        *,
        session_id: str | None = None,
        now: datetime,
        limit: int = 10,
    ) -> list[str]:
        jobs = self.repository.claim_outbox_jobs(db, session_id=session_id, now=now, limit=limit)
        completed: list[str] = []
        for job in jobs:
            try:
                payload = self.repository.decode_outbox_payload(job)
                if job.job_kind == "summary_generation":
                    self._generate_summary(db, session_id=job.session_id, message_id=job.message_id)
                elif job.job_kind == "memory_extraction" and self.memory_service is not None:
                    self._extract_memory(db, payload=payload)
                elif job.job_kind == "retrieval_index" and self.retrieval_service is not None:
                    self._index_retrieval(db, payload=payload)
                elif job.job_kind == "attachment_extraction" and self.attachment_extraction_service is not None:
                    self._extract_attachment(db, payload=payload)
                elif job.job_kind == "continuity_repair":
                    self._generate_summary(db, session_id=job.session_id, message_id=job.message_id)
                self.repository.complete_outbox_job(db, job_id=job.id)
                completed.append(job.job_kind)
            except Exception as exc:
                self.repository.fail_outbox_job(db, job_id=job.id, error=str(exc))
        return completed

    def _generate_summary(self, db: Session, *, session_id: str, message_id: int) -> SummarySnapshotLike | None:
        existing = self.repository.get_latest_valid_summary_snapshot(
            db,
            session_id=session_id,
            message_id=message_id + 1,
        )
        base_message_id = 1 if existing is None else existing.through_message_id + 1
        rows = self.repository.list_messages(db, session_id=session_id, limit=max(message_id, 1), before_message_id=None)
        rows = [row for row in rows if base_message_id <= row.id <= message_id]
        if len(rows) < 4:
            return None
        summary_text = " | ".join(f"{row.role}:{row.content}" for row in rows[:8])
        snapshot = self.repository.append_summary_snapshot(
            db,
            session_id=session_id,
            base_message_id=rows[0].id,
            through_message_id=rows[-1].id,
            source_watermark_message_id=message_id,
            summary_text=summary_text,
            summary_metadata={"message_ids": [row.id for row in rows]},
        )
        self.repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="memory_extraction",
            job_dedupe_key=f"memory_extraction:summary:{snapshot.id}",
            payload={
                "job_kind": "memory_extraction",
                "source": {"source_kind": "summary_snapshot", "source_id": snapshot.id, "strategy_id": "memory-v1"},
            },
        )
        self.repository.enqueue_outbox_job(
            db,
            session_id=session_id,
            message_id=message_id,
            job_kind="retrieval_index",
            job_dedupe_key=f"retrieval_index:summary:{snapshot.id}",
            payload={
                "job_kind": "retrieval_index",
                "source": {"source_kind": "summary_snapshot", "source_id": snapshot.id, "strategy_id": "lexical-v1"},
            },
        )
        return snapshot

    def _extract_memory(self, db: Session, *, payload: dict[str, Any]) -> None:
        source = payload.get("source", {})
        memory = None
        if source.get("source_kind") == "message":
            memory = self.memory_service.extract_from_message(db=db, repository=self.repository, message_id=source["source_id"])
        elif source.get("source_kind") == "summary_snapshot":
            memory = self.memory_service.extract_from_summary(
                db=db,
                repository=self.repository,
                summary_snapshot_id=source["source_id"],
            )
        if memory is not None and memory.status == "active":
            self.repository.enqueue_outbox_job(
                db,
                session_id=memory.session_id,
                message_id=memory.source_through_message_id or memory.source_message_id or 0,
                job_kind="retrieval_index",
                job_dedupe_key=f"retrieval_index:memory:{memory.id}",
                payload={
                    "job_kind": "retrieval_index",
                    "source": {"source_kind": "memory", "source_id": memory.id, "strategy_id": "lexical-v1"},
                },
            )

    def _index_retrieval(self, db: Session, *, payload: dict[str, Any]) -> None:
        source = payload.get("source", {})
        if source.get("source_kind") == "message":
            self.retrieval_service.index_message(db=db, repository=self.repository, message_id=source["source_id"])
        elif source.get("source_kind") == "summary_snapshot":
            self.retrieval_service.index_summary(
                db=db,
                repository=self.repository,
                summary_snapshot_id=source["source_id"],
            )
        elif source.get("source_kind") == "memory":
            self.retrieval_service.index_memory(db=db, repository=self.repository, memory_id=source["source_id"])
        elif source.get("source_kind") == "attachment_extraction":
            self.retrieval_service.index_attachment_extraction(
                db=db,
                repository=self.repository,
                attachment_extraction_id=source["source_id"],
            )

    def _extract_attachment(self, db: Session, *, payload: dict[str, Any]) -> None:
        source = payload.get("source", {})
        extraction = self.attachment_extraction_service.extract_attachment(
            db=db,
            repository=self.repository,
            attachment_id=source["source_id"],
            extractor_kind=source.get("extractor_kind", "default"),
            same_run=False,
        )
        if extraction is not None and extraction.status == "completed":
            self.repository.enqueue_outbox_job(
                db,
                session_id=extraction.session_id,
                message_id=payload.get("message_id") or 0,
                job_kind="retrieval_index",
                job_dedupe_key=f"retrieval_index:attachment_extraction:{extraction.id}",
                payload={
                    "job_kind": "retrieval_index",
                    "source": {
                        "source_kind": "attachment_extraction",
                        "source_id": extraction.id,
                        "strategy_id": "lexical-v1",
                    },
                },
            )

    @staticmethod
    def decode_manifest(record: Any) -> dict[str, Any]:
        return json.loads(record.manifest_json)


SummarySnapshotLike = Any
