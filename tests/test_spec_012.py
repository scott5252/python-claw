from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from sqlalchemy import select, func

from src.channels.adapters.base import ChannelSendError
from src.channels.adapters.slack import SlackAdapter
from src.channels.adapters.telegram import TelegramAdapter
from src.config.settings import ChannelAccountConfig, Settings
from src.db.models import MessageRecord, SessionRecord
from src.domain.schemas import DurableTransportAddress
from src.sessions.repository import SessionRepository


def _slack_signature(*, body: bytes, timestamp: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), b"v0:" + timestamp.encode("utf-8") + b":" + body, hashlib.sha256)
    return "v0=" + digest.hexdigest()


def test_channel_account_registry_validates_real_accounts() -> None:
    settings = Settings(
        database_url="sqlite://",
        channel_accounts=[
            ChannelAccountConfig(
                channel_account_id="prod-slack",
                channel_kind="slack",
                mode="real",
                outbound_token="xoxb-token",
                signing_secret="signing-secret",
            ),
            ChannelAccountConfig(
                channel_account_id="prod-webchat",
                channel_kind="webchat",
                mode="real",
                webchat_client_token="webchat-secret",
            ),
        ],
    )
    slack_account = settings.get_channel_account(channel_kind="slack", channel_account_id="prod-slack")
    assert slack_account.mode == "real"


def test_slack_provider_route_verifies_challenge_without_transcript_writes(client, session_manager) -> None:
    payload = {"type": "url_verification", "challenge": "challenge-token", "api_app_id": "acct"}
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/providers/slack/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": "12345",
            "X-Slack-Signature": _slack_signature(body=body, timestamp="12345", secret="fake-slack-secret"),
        },
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-token"}
    with session_manager.session() as db:
        assert db.scalar(select(func.count()).select_from(SessionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(MessageRecord)) == 0


def test_slack_provider_route_accepts_message_and_dedupes(client, session_manager) -> None:
    payload = {
        "type": "event_callback",
        "api_app_id": "acct",
        "event": {
            "type": "message",
            "channel": "C123",
            "channel_type": "channel",
            "user": "U456",
            "text": "hello from slack",
            "ts": "1710000000.000100",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": "12345",
        "X-Slack-Signature": _slack_signature(body=body, timestamp="12345", secret="fake-slack-secret"),
    }
    first = client.post("/providers/slack/events", content=body, headers=headers)
    second = client.post("/providers/slack/events", content=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["dedupe_status"] == "accepted"
    assert second.json()["dedupe_status"] == "duplicate"


def test_telegram_provider_route_ignores_unsupported_updates(client) -> None:
    response = client.post(
        "/providers/telegram/webhook/acct",
        json={"edited_message": {"message_id": 1}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "fake-telegram-secret"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webchat_inbound_and_polling_surface_persisted_deliveries(client, drain_queue) -> None:
    accepted = client.post(
        "/providers/webchat/accounts/acct/messages",
        json={"actor_id": "browser-user", "content": "hello", "peer_id": "browser-user", "stream_id": "stream-1", "message_id": "client-msg-1"},
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
    )
    assert accepted.status_code == 202
    drain_queue()
    poll = client.get(
        "/providers/webchat/accounts/acct/poll",
        params={"stream_id": "stream-1"},
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
    )
    assert poll.status_code == 200
    body = poll.json()
    assert body["items"]
    assert body["items"][0]["payload"]["text"].startswith("Received:")
    next_cursor = body["next_after_delivery_id"]
    empty = client.get(
        "/providers/webchat/accounts/acct/poll",
        params={"stream_id": "stream-1", "after_delivery_id": next_cursor},
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []


def test_real_slack_adapter_maps_provider_error_to_structured_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat.postMessage")
        return httpx.Response(429, json={"ok": False, "error": "ratelimited"})

    adapter = SlackAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    account = ChannelAccountConfig(
        channel_account_id="prod-slack",
        channel_kind="slack",
        mode="real",
        outbound_token="token",
        signing_secret="secret",
        base_url="https://slack.test",
    )
    try:
        adapter.send_text_chunk(
            account=account,
            transport_address=DurableTransportAddress(provider="slack", address_key="C123", metadata={}),
            session_id="session-1",
            text="hello",
            reply_to_external_id=None,
            provider_idempotency_key="delivery-1",
        )
    except ChannelSendError as exc:
        assert exc.error_code == "provider_rate_limited"
        assert exc.retryable is True
    else:
        raise AssertionError("expected ChannelSendError")


def test_real_telegram_adapter_uses_chat_transport_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["chat_id"] == "1234"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    adapter = TelegramAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    account = ChannelAccountConfig(
        channel_account_id="prod-telegram",
        channel_kind="telegram",
        mode="real",
        outbound_token="token",
        webhook_secret="secret",
        base_url="https://telegram.test",
    )
    result = adapter.send_text_chunk(
        account=account,
        transport_address=DurableTransportAddress(provider="telegram", address_key="1234", metadata={}),
        session_id="session-1",
        text="hello",
        reply_to_external_id="telegram:1234:55",
        provider_idempotency_key="delivery-2",
    )
    assert result.provider_message_id == "telegram:1234:99"
