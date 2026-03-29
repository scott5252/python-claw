from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import RateLimitCounterRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    retry_after_seconds: int | None
    used: int
    limit: int


@dataclass
class QuotaService:
    def check_and_increment(
        self,
        db: Session,
        *,
        scope_kind: str,
        scope_key: str,
        limit: int,
        window_seconds: int,
        current_time: datetime | None = None,
    ) -> QuotaDecision:
        now = current_time or utc_now()
        normalized_key = scope_key.strip()
        if not normalized_key:
            normalized_key = "unknown"
        window_start_epoch = int(now.timestamp()) // window_seconds * window_seconds
        window_start = datetime.fromtimestamp(window_start_epoch, tz=timezone.utc)
        row = db.scalar(
            select(RateLimitCounterRecord).where(
                RateLimitCounterRecord.scope_kind == scope_kind,
                RateLimitCounterRecord.scope_key == normalized_key,
                RateLimitCounterRecord.window_seconds == window_seconds,
                RateLimitCounterRecord.window_start == window_start,
            )
        )
        if row is None:
            row = RateLimitCounterRecord(
                scope_kind=scope_kind,
                scope_key=normalized_key,
                window_seconds=window_seconds,
                window_start=window_start,
                count=0,
                last_seen_at=now,
            )
            db.add(row)
            db.flush()
        row.last_seen_at = now
        if row.count >= limit:
            retry_after = max(1, int((window_start + timedelta(seconds=window_seconds) - now).total_seconds()))
            return QuotaDecision(allowed=False, retry_after_seconds=retry_after, used=row.count, limit=limit)
        row.count += 1
        db.flush()
        return QuotaDecision(allowed=True, retry_after_seconds=None, used=row.count, limit=limit)
