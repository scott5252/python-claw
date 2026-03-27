from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from src.channels.adapters.base import ChannelAdapter, ChannelCapabilities, ChannelSendError, SendResult
from src.config.settings import ChannelAccountConfig
from src.domain.schemas import CanonicalAttachmentInput, DurableTransportAddress


class SlackAdapter(ChannelAdapter):
    channel_kind = "slack"
    capabilities = ChannelCapabilities(
        max_text_chars=3000,
        supports_reply=True,
        supports_media=True,
        supports_voice=False,
    )

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=10.0)

    def verify_request(self, *, body: bytes, timestamp: str | None, signature: str | None, signing_secret: str | None) -> bool:
        if not signing_secret or not timestamp or not signature:
            return False
        basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
        expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def translate_inbound(self, *, payload: dict[str, Any], channel_account_id: str) -> dict[str, Any] | None:
        if payload.get("type") != "event_callback":
            return None
        event = payload.get("event") or {}
        if event.get("type") != "message" or event.get("subtype"):
            return None
        conversation_id = str(event.get("channel", "")).strip()
        message_ts = str(event.get("ts", "")).strip()
        sender_id = str(event.get("user", "")).strip()
        if not conversation_id or not message_ts or not sender_id:
            raise ValueError("unsupported slack event payload")
        channel_type = str(event.get("channel_type", "")).strip()
        external_message_id = f"slack:{conversation_id}:{message_ts}"
        transport_address = {
            "conversation_id": conversation_id,
            "thread_ts": str(event.get("thread_ts") or ""),
            "channel_type": channel_type,
        }
        return {
            "channel_kind": "slack",
            "channel_account_id": channel_account_id,
            "external_message_id": external_message_id,
            "sender_id": sender_id,
            "content": str(event.get("text", "")),
            "peer_id": conversation_id if channel_type == "im" else None,
            "group_id": None if channel_type == "im" else conversation_id,
            "attachments": self._translate_attachments(event),
            "transport_address_key": conversation_id,
            "transport_address": {
                "provider": "slack",
                "address_key": conversation_id,
                "metadata": transport_address,
            },
        }

    def send_text_chunk(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        text: str,
        reply_to_external_id: str | None,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        _ = session_id
        if account.mode == "fake":
            return SendResult(
                provider_message_id=f"slack:{transport_address.address_key}:{provider_idempotency_key or abs(hash(text))}",
                provider_metadata={"transport_mode": "fake"},
            )
        thread_ts = self._resolve_reply_target(reply_to_external_id=reply_to_external_id, transport_address=transport_address)
        response = self.client.post(
            f"{account.base_url or 'https://slack.com/api'}/chat.postMessage",
            headers={
                "Authorization": f"Bearer {account.outbound_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "channel": transport_address.address_key,
                "text": text,
                "thread_ts": thread_ts,
                "metadata": {"event_type": "python_claw.delivery", "event_payload": {"idempotency_key": provider_idempotency_key}},
            },
        )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok"):
            raise self._send_error(payload=payload, status_code=response.status_code)
        return SendResult(
            provider_message_id=f"slack:{transport_address.address_key}:{payload['ts']}",
            provider_metadata={"thread_ts": payload.get("ts"), "transport_mode": "real"},
        )

    def send_media(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        storage_key: str,
        mime_type: str,
        caption: str | None,
        voice: bool,
        reply_to_external_id: str | None,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        _ = (mime_type, voice, session_id)
        if account.mode == "fake":
            return SendResult(
                provider_message_id=f"slack-media:{transport_address.address_key}:{provider_idempotency_key or abs(hash(storage_key))}",
                provider_metadata={"transport_mode": "fake"},
            )
        response = self.client.post(
            f"{account.base_url or 'https://slack.com/api'}/files.remote.add",
            headers={"Authorization": f"Bearer {account.outbound_token}"},
            json={
                "channels": transport_address.address_key,
                "external_id": storage_key,
                "external_url": storage_key,
                "title": caption or storage_key.rsplit("/", 1)[-1],
                "thread_ts": self._resolve_reply_target(
                    reply_to_external_id=reply_to_external_id,
                    transport_address=transport_address,
                ),
            },
        )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok"):
            raise self._send_error(payload=payload, status_code=response.status_code)
        file_id = ((payload.get("file") or {}).get("id")) or storage_key
        return SendResult(
            provider_message_id=f"slack-media:{transport_address.address_key}:{file_id}",
            provider_metadata={"file_id": file_id, "transport_mode": "real"},
        )

    def _translate_attachments(self, event: dict[str, Any]) -> list[CanonicalAttachmentInput]:
        files = event.get("files") or []
        attachments: list[CanonicalAttachmentInput] = []
        for item in files:
            url = item.get("url_private_download") or item.get("url_private")
            if not url:
                continue
            attachments.append(
                CanonicalAttachmentInput(
                    external_attachment_id=str(item.get("id") or ""),
                    source_url=str(url),
                    mime_type=str(item.get("mimetype") or "application/octet-stream"),
                    filename=item.get("name"),
                    byte_size=item.get("size"),
                    provider_metadata={"title": item.get("title")},
                )
            )
        return attachments

    def _resolve_reply_target(
        self,
        *,
        reply_to_external_id: str | None,
        transport_address: DurableTransportAddress,
    ) -> str | None:
        if reply_to_external_id and reply_to_external_id.startswith("slack:"):
            return reply_to_external_id.rsplit(":", 1)[-1]
        thread_ts = transport_address.metadata.get("thread_ts")
        return str(thread_ts).strip() or None

    def _send_error(self, *, payload: dict[str, Any], status_code: int) -> ChannelSendError:
        error = str(payload.get("error") or f"http_{status_code}")
        retryable = error in {"ratelimited", "internal_error", "service_unavailable"} or status_code >= 500
        if error in {"invalid_auth", "not_authed"}:
            code = "provider_auth_failed"
        elif error == "ratelimited":
            code = "provider_rate_limited"
        elif retryable:
            code = "provider_unavailable"
        else:
            code = "provider_invalid_request"
        return ChannelSendError(
            error_code=code,
            detail=error,
            retryable=retryable,
            provider_metadata={"status_code": status_code},
        )
