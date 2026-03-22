from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import DedupeStatus, InboundDedupeRecord


class IdempotencyConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class IdempotencyKey:
    channel_kind: str
    channel_account_id: str
    external_message_id: str


@dataclass(frozen=True)
class ClaimAccepted:
    dedupe_id: int


@dataclass(frozen=True)
class DuplicateReplay:
    session_id: str
    message_id: int


class IdempotencyService:
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def claim(
        self,
        db: Session,
        *,
        key: IdempotencyKey,
        retention_days: int,
        stale_after_seconds: int,
    ) -> ClaimAccepted | DuplicateReplay:
        existing = db.scalar(
            select(InboundDedupeRecord).where(
                InboundDedupeRecord.channel_kind == key.channel_kind,
                InboundDedupeRecord.channel_account_id == key.channel_account_id,
                InboundDedupeRecord.external_message_id == key.external_message_id,
            )
        )
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=retention_days)

        if existing is None:
            record = InboundDedupeRecord(
                status=DedupeStatus.CLAIMED.value,
                channel_kind=key.channel_kind,
                channel_account_id=key.channel_account_id,
                external_message_id=key.external_message_id,
                expires_at=expires_at,
            )
            db.add(record)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return self.claim(
                    db,
                    key=key,
                    retention_days=retention_days,
                    stale_after_seconds=stale_after_seconds,
                )
            return ClaimAccepted(dedupe_id=record.id)

        if existing.status == DedupeStatus.COMPLETED.value and existing.session_id and existing.message_id:
            return DuplicateReplay(session_id=existing.session_id, message_id=existing.message_id)

        age_seconds = (now - self._as_utc(existing.first_seen_at)).total_seconds()
        if age_seconds >= stale_after_seconds:
            existing.first_seen_at = now
            existing.expires_at = expires_at
            db.flush()
            return ClaimAccepted(dedupe_id=existing.id)

        raise IdempotencyConflictError("matching dedupe identity is already claimed")

    def finalize(
        self,
        db: Session,
        *,
        dedupe_id: int,
        session_id: str,
        message_id: int,
        expires_at: datetime,
    ) -> InboundDedupeRecord:
        record = db.get(InboundDedupeRecord, dedupe_id)
        if record is None:
            raise IdempotencyConflictError("dedupe record not found during finalize")
        record.status = DedupeStatus.COMPLETED.value
        record.session_id = session_id
        record.message_id = message_id
        record.expires_at = expires_at
        db.flush()
        return record
