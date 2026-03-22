from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.db.models import DedupeStatus, InboundDedupeRecord
from src.gateway.idempotency import (
    ClaimAccepted,
    DuplicateReplay,
    IdempotencyConflictError,
    IdempotencyKey,
    IdempotencyService,
)


def test_first_claim_and_finalize_flow(session_manager) -> None:
    service = IdempotencyService()
    with session_manager.session() as db:
        result = service.claim(
            db,
            key=IdempotencyKey("slack", "acct", "msg-1"),
            retention_days=30,
            stale_after_seconds=60,
        )
        assert isinstance(result, ClaimAccepted)
        service.finalize(
            db,
            dedupe_id=result.dedupe_id,
            session_id="session-1",
            message_id=42,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.commit()

    with session_manager.session() as db:
        replay = service.claim(
            db,
            key=IdempotencyKey("slack", "acct", "msg-1"),
            retention_days=30,
            stale_after_seconds=60,
        )
        assert isinstance(replay, DuplicateReplay)
        assert replay.session_id == "session-1"
        assert replay.message_id == 42


def test_non_stale_claimed_row_blocks_duplicate_work(session_manager) -> None:
    service = IdempotencyService()
    with session_manager.session() as db:
        accepted = service.claim(
            db,
            key=IdempotencyKey("slack", "acct", "msg-2"),
            retention_days=30,
            stale_after_seconds=60,
        )
        assert isinstance(accepted, ClaimAccepted)
        db.commit()

    with session_manager.session() as db:
        with pytest.raises(IdempotencyConflictError):
            service.claim(
                db,
                key=IdempotencyKey("slack", "acct", "msg-2"),
                retention_days=30,
                stale_after_seconds=60,
            )


def test_stale_claimed_row_is_recoverable(session_manager) -> None:
    service = IdempotencyService()
    with session_manager.session() as db:
        record = InboundDedupeRecord(
            status=DedupeStatus.CLAIMED.value,
            channel_kind="slack",
            channel_account_id="acct",
            external_message_id="msg-3",
            first_seen_at=datetime.now(timezone.utc) - timedelta(seconds=120),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(record)
        db.commit()

    with session_manager.session() as db:
        result = service.claim(
            db,
            key=IdempotencyKey("slack", "acct", "msg-3"),
            retention_days=30,
            stale_after_seconds=60,
        )
        assert isinstance(result, ClaimAccepted)
        assert result.dedupe_id == 1
