from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


@dataclass
class OutboxWorker:
    repository: Any

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
                if job.job_kind == "summary_generation":
                    self._generate_summary(db, session_id=job.session_id, message_id=job.message_id)
                self.repository.complete_outbox_job(db, job_id=job.id)
                completed.append(job.job_kind)
            except Exception as exc:
                self.repository.fail_outbox_job(db, job_id=job.id, error=str(exc))
        return completed

    def _generate_summary(self, db: Session, *, session_id: str, message_id: int) -> None:
        existing = self.repository.get_latest_valid_summary_snapshot(
            db,
            session_id=session_id,
            message_id=message_id + 1,
        )
        base_message_id = 1 if existing is None else existing.through_message_id + 1
        rows = self.repository.list_messages(
            db,
            session_id=session_id,
            limit=max(message_id, 1),
            before_message_id=None,
        )
        rows = [row for row in rows if base_message_id <= row.id <= message_id]
        if len(rows) < 4:
            return
        summary_text = " | ".join(f"{row.role}:{row.content}" for row in rows[:8])
        self.repository.append_summary_snapshot(
            db,
            session_id=session_id,
            base_message_id=rows[0].id,
            through_message_id=rows[-1].id,
            source_watermark_message_id=message_id,
            summary_text=summary_text,
            summary_metadata={"message_ids": [row.id for row in rows]},
        )

    @staticmethod
    def decode_manifest(record: Any) -> dict[str, Any]:
        return json.loads(record.manifest_json)
