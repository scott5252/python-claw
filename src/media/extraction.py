from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session


class AttachmentExtractionRetryableError(RuntimeError):
    pass


@dataclass
class MediaExtractionService:
    storage_root: Path
    strategy_id: str
    same_run_max_bytes: int
    same_run_pdf_page_limit: int
    same_run_timeout_seconds: int

    def extract_attachment(
        self,
        *,
        db: Session,
        repository: Any,
        attachment_id: int,
        extractor_kind: str = "default",
        same_run: bool = False,
    ):
        attachment = repository.get_message_attachment(db, attachment_id=attachment_id)
        if attachment is None or attachment.normalization_status != "stored" or not attachment.storage_key:
            raise AttachmentExtractionRetryableError("missing normalized attachment state")

        existing = repository.get_attachment_extraction(
            db,
            attachment_id=attachment_id,
            extractor_kind=extractor_kind,
            derivation_strategy_id=self.strategy_id,
        )
        if existing is not None and existing.status in {"completed", "failed", "unsupported"}:
            return existing

        record = repository.upsert_attachment_extraction(
            db,
            session_id=attachment.session_id,
            attachment_id=attachment.id,
            extractor_kind=extractor_kind,
            derivation_strategy_id=self.strategy_id,
            status="pending",
        )
        path = self.storage_root / attachment.storage_key
        if not path.exists():
            raise AttachmentExtractionRetryableError("normalized attachment payload missing from storage")

        started = time.monotonic()
        try:
            if attachment.mime_type.startswith("text/"):
                content_text = self._extract_text(path=path, max_bytes=self.same_run_max_bytes if same_run else None)
                metadata = {"mode": "text", "same_run": same_run}
                return repository.upsert_attachment_extraction(
                    db,
                    session_id=attachment.session_id,
                    attachment_id=attachment.id,
                    extractor_kind=extractor_kind,
                    derivation_strategy_id=self.strategy_id,
                    status="completed",
                    content_text=content_text,
                    content_metadata=metadata,
                )
            if attachment.mime_type == "application/pdf":
                content_text = self._extract_pdf_text(path=path, same_run=same_run)
                metadata = {"mode": "pdf_text", "same_run": same_run}
                return repository.upsert_attachment_extraction(
                    db,
                    session_id=attachment.session_id,
                    attachment_id=attachment.id,
                    extractor_kind=extractor_kind,
                    derivation_strategy_id=self.strategy_id,
                    status="completed",
                    content_text=content_text,
                    content_metadata=metadata,
                )
            return repository.upsert_attachment_extraction(
                db,
                session_id=attachment.session_id,
                attachment_id=attachment.id,
                extractor_kind=extractor_kind,
                derivation_strategy_id=self.strategy_id,
                status="unsupported",
                content_metadata={"mime_type": attachment.mime_type, "same_run": same_run},
                error_detail="unsupported attachment type for extraction",
            )
        except UnicodeDecodeError:
            return repository.upsert_attachment_extraction(
                db,
                session_id=attachment.session_id,
                attachment_id=attachment.id,
                extractor_kind=extractor_kind,
                derivation_strategy_id=self.strategy_id,
                status="failed",
                content_metadata={"same_run": same_run},
                error_detail="attachment text decoding failed",
            )
        except ValueError as exc:
            return repository.upsert_attachment_extraction(
                db,
                session_id=attachment.session_id,
                attachment_id=attachment.id,
                extractor_kind=extractor_kind,
                derivation_strategy_id=self.strategy_id,
                status="failed",
                content_metadata={"same_run": same_run},
                error_detail=str(exc),
            )
        finally:
            elapsed = time.monotonic() - started
            if same_run and elapsed > self.same_run_timeout_seconds:
                repository.upsert_attachment_extraction(
                    db,
                    session_id=attachment.session_id,
                    attachment_id=attachment.id,
                    extractor_kind=extractor_kind,
                    derivation_strategy_id=self.strategy_id,
                    status="failed",
                    content_metadata={"same_run": True},
                    error_detail="same-run extraction timed out",
                )

    def _extract_text(self, *, path: Path, max_bytes: int | None) -> str:
        payload = path.read_bytes()
        if max_bytes is not None and len(payload) > max_bytes:
            raise ValueError("attachment exceeds same-run extraction size limit")
        return payload.decode("utf-8").strip()

    def _extract_pdf_text(self, *, path: Path, same_run: bool) -> str:
        payload = path.read_bytes()
        if same_run and len(payload) > self.same_run_max_bytes:
            raise ValueError("attachment exceeds same-run extraction size limit")
        page_count = payload.count(b"/Page") or 1
        if same_run and page_count > self.same_run_pdf_page_limit:
            raise ValueError("attachment exceeds same-run pdf page limit")
        decoded = payload.decode("latin-1")
        chunks = [item.strip() for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9 ,.:'\"()/_-]{5,}", decoded)]
        text = " ".join(chunks).strip()
        if not text:
            raise ValueError("pdf did not contain extractable text")
        return text[:4000]
