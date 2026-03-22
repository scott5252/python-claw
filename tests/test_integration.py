from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.config.settings import Settings
from src.db.base import Base
from src.db.models import DedupeStatus, InboundDedupeRecord
from src.db.session import DatabaseSessionManager


def test_restart_safe_session_reuse_and_duplicate_replay(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    settings = Settings(
        database_url=database_url,
        dedupe_stale_after_seconds=1,
        messages_page_default_limit=2,
        messages_page_max_limit=3,
    )
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app1 = create_app(settings=settings, session_manager=manager)
    client1 = TestClient(app1)
    first = client1.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    session_id = first.json()["session_id"]
    message_id = first.json()["message_id"]

    manager2 = DatabaseSessionManager(database_url)
    app2 = create_app(settings=settings, session_manager=manager2)
    client2 = TestClient(app2)

    duplicate = client2.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    assert duplicate.json()["session_id"] == session_id
    assert duplicate.json()["message_id"] == message_id

    next_message = client2.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "follow-up",
            "peer_id": "peer",
        },
    )
    assert next_message.json()["session_id"] == session_id


def test_stale_claimed_recovery_and_history_paging(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale.db'}"
    settings = Settings(database_url=database_url, dedupe_stale_after_seconds=1)
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    with manager.session() as db:
        db.add(
            InboundDedupeRecord(
                status=DedupeStatus.CLAIMED.value,
                channel_kind="slack",
                channel_account_id="acct",
                external_message_id="msg-stale",
                first_seen_at=datetime.now(timezone.utc) - timedelta(seconds=120),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        db.commit()

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    recovered = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-stale",
            "sender_id": "sender",
            "content": "one",
            "peer_id": "peer",
        },
    )
    assert recovered.status_code == 201
    session_id = recovered.json()["session_id"]

    client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "two",
            "peer_id": "peer",
        },
    )
    client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-3",
            "sender_id": "sender",
            "content": "three",
            "peer_id": "peer",
        },
    )

    page_one = client.get(f"/sessions/{session_id}/messages", params={"limit": 2})
    body_one = page_one.json()
    assert [item["content"] for item in body_one["items"]] == ["two", "three"]
    assert body_one["next_before_message_id"] == 2

    page_two = client.get(
        f"/sessions/{session_id}/messages",
        params={"limit": 2, "before_message_id": 2},
    )
    body_two = page_two.json()
    assert [item["content"] for item in body_two["items"]] == ["one"]
