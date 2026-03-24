from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from sqlalchemy.orm import Session


class AttachmentNormalizationRetryableError(Exception):
    pass


@dataclass
class MediaProcessor:
    storage_root: Path
    storage_bucket: str
    retention_days: int
    max_bytes: int
    allowed_schemes: tuple[str, ...]
    allowed_mime_prefixes: tuple[str, ...]

    def normalize_message_attachments(self, *, db: Session, repository, session_id: str, message_id: int) -> list[int]:
        inbound_rows = repository.list_inbound_attachments(db, message_id=message_id)
        stored_ids: list[int] = []
        self.storage_root.mkdir(parents=True, exist_ok=True)
        for inbound in inbound_rows:
            latest = repository.get_latest_message_attachment_for_inbound(
                db,
                inbound_message_attachment_id=inbound.id,
            )
            if latest is not None and latest.normalization_status in {"stored", "rejected"}:
                if latest.normalization_status == "stored":
                    stored_ids.append(latest.id)
                continue
            try:
                stored = self._normalize_one(
                    db=db,
                    repository=repository,
                    inbound=inbound,
                )
                if stored is not None:
                    stored_ids.append(stored.id)
            except AttachmentNormalizationRetryableError:
                raise
        return stored_ids

    def _normalize_one(self, *, db: Session, repository, inbound):
        provider_metadata = json.loads(inbound.provider_metadata_json)
        parsed = urlparse(inbound.source_url)
        if parsed.scheme not in self.allowed_schemes:
            repository.append_message_attachment(
                db,
                inbound_attachment_id=inbound.id,
                message_id=inbound.message_id,
                session_id=inbound.session_id,
                ordinal=inbound.ordinal,
                external_attachment_id=inbound.external_attachment_id,
                source_url=inbound.source_url,
                storage_key=None,
                storage_bucket=None,
                mime_type=inbound.mime_type,
                media_kind=self._classify_media_kind(inbound.mime_type),
                filename=inbound.filename,
                byte_size=inbound.byte_size,
                sha256=None,
                normalization_status="rejected",
                retention_expires_at=None,
                provider_metadata=provider_metadata,
                error_detail=f"unsupported scheme: {parsed.scheme}",
            )
            return None
        if not self._mime_allowed(inbound.mime_type):
            repository.append_message_attachment(
                db,
                inbound_attachment_id=inbound.id,
                message_id=inbound.message_id,
                session_id=inbound.session_id,
                ordinal=inbound.ordinal,
                external_attachment_id=inbound.external_attachment_id,
                source_url=inbound.source_url,
                storage_key=None,
                storage_bucket=None,
                mime_type=inbound.mime_type,
                media_kind=self._classify_media_kind(inbound.mime_type),
                filename=inbound.filename,
                byte_size=inbound.byte_size,
                sha256=None,
                normalization_status="rejected",
                retention_expires_at=None,
                provider_metadata=provider_metadata,
                error_detail=f"unsupported mime type: {inbound.mime_type}",
            )
            return None
        if inbound.byte_size is not None and inbound.byte_size > self.max_bytes:
            repository.append_message_attachment(
                db,
                inbound_attachment_id=inbound.id,
                message_id=inbound.message_id,
                session_id=inbound.session_id,
                ordinal=inbound.ordinal,
                external_attachment_id=inbound.external_attachment_id,
                source_url=inbound.source_url,
                storage_key=None,
                storage_bucket=None,
                mime_type=inbound.mime_type,
                media_kind=self._classify_media_kind(inbound.mime_type),
                filename=inbound.filename,
                byte_size=inbound.byte_size,
                sha256=None,
                normalization_status="rejected",
                retention_expires_at=None,
                provider_metadata=provider_metadata,
                error_detail="attachment exceeds configured size limit",
            )
            return None
        try:
            with urlopen(inbound.source_url) as response:
                payload = response.read(self.max_bytes + 1)
        except Exception as exc:
            repository.append_message_attachment(
                db,
                inbound_attachment_id=inbound.id,
                message_id=inbound.message_id,
                session_id=inbound.session_id,
                ordinal=inbound.ordinal,
                external_attachment_id=inbound.external_attachment_id,
                source_url=inbound.source_url,
                storage_key=None,
                storage_bucket=None,
                mime_type=inbound.mime_type,
                media_kind=self._classify_media_kind(inbound.mime_type),
                filename=inbound.filename,
                byte_size=inbound.byte_size,
                sha256=None,
                normalization_status="failed",
                retention_expires_at=None,
                provider_metadata=provider_metadata,
                error_detail=str(exc),
            )
            raise AttachmentNormalizationRetryableError(str(exc)) from exc
        if len(payload) > self.max_bytes:
            repository.append_message_attachment(
                db,
                inbound_attachment_id=inbound.id,
                message_id=inbound.message_id,
                session_id=inbound.session_id,
                ordinal=inbound.ordinal,
                external_attachment_id=inbound.external_attachment_id,
                source_url=inbound.source_url,
                storage_key=None,
                storage_bucket=None,
                mime_type=inbound.mime_type,
                media_kind=self._classify_media_kind(inbound.mime_type),
                filename=inbound.filename,
                byte_size=len(payload),
                sha256=None,
                normalization_status="rejected",
                retention_expires_at=None,
                provider_metadata=provider_metadata,
                error_detail="attachment exceeds configured size limit",
            )
            return None
        digest = hashlib.sha256(payload).hexdigest()
        extension = self._suffix_for_filename(inbound.filename, inbound.mime_type)
        storage_key = f"{inbound.session_id}/{inbound.message_id}/{inbound.ordinal}-{digest[:16]}{extension}"
        output_path = self.storage_root / storage_key
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        return repository.append_message_attachment(
            db,
            inbound_attachment_id=inbound.id,
            message_id=inbound.message_id,
            session_id=inbound.session_id,
            ordinal=inbound.ordinal,
            external_attachment_id=inbound.external_attachment_id,
            source_url=inbound.source_url,
            storage_key=storage_key,
            storage_bucket=self.storage_bucket,
            mime_type=inbound.mime_type,
            media_kind=self._classify_media_kind(inbound.mime_type),
            filename=inbound.filename,
            byte_size=len(payload),
            sha256=digest,
            normalization_status="stored",
            retention_expires_at=datetime.now(timezone.utc) + timedelta(days=self.retention_days),
            provider_metadata=provider_metadata,
        )

    def _mime_allowed(self, mime_type: str) -> bool:
        return any(
            mime_type.startswith(prefix) if prefix.endswith("/") else mime_type == prefix
            for prefix in self.allowed_mime_prefixes
        )

    def _classify_media_kind(self, mime_type: str) -> str:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type.startswith("text/") or mime_type.startswith("application/"):
            return "document"
        return "other"

    def _suffix_for_filename(self, filename: str | None, mime_type: str) -> str:
        if filename and "." in filename:
            return f".{filename.rsplit('.', 1)[-1]}"
        if mime_type == "application/pdf":
            return ".pdf"
        if mime_type.startswith("image/"):
            return f".{mime_type.split('/', 1)[1]}"
        if mime_type.startswith("audio/"):
            return f".{mime_type.split('/', 1)[1]}"
        return ""
