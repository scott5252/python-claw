from __future__ import annotations

from typing import Any

import httpx

from src.channels.adapters.base import ChannelAdapter, ChannelCapabilities, ChannelSendError, SendResult
from src.config.settings import ChannelAccountConfig
from src.domain.schemas import CanonicalAttachmentInput, DurableTransportAddress


class TelegramAdapter(ChannelAdapter):
    channel_kind = "telegram"
    capabilities = ChannelCapabilities(
        max_text_chars=4096,
        supports_reply=True,
        supports_media=True,
        supports_voice=True,
    )

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=10.0)

    def verify_request(self, *, secret_token: str | None, expected_secret: str | None) -> bool:
        return bool(expected_secret and secret_token and secret_token == expected_secret)

    def translate_inbound(self, *, payload: dict[str, Any], channel_account_id: str) -> dict[str, Any] | None:
        message = payload.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = str(chat.get("id") or "").strip()
        message_id = str(message.get("message_id") or "").strip()
        sender_id = str(sender.get("id") or "").strip()
        if not chat_id or not message_id or not sender_id:
            raise ValueError("unsupported telegram payload")
        chat_type = str(chat.get("type") or "").strip()
        return {
            "channel_kind": "telegram",
            "channel_account_id": channel_account_id,
            "external_message_id": f"telegram:{chat_id}:{message_id}",
            "sender_id": sender_id,
            "content": str(message.get("text") or message.get("caption") or ""),
            "peer_id": chat_id if chat_type == "private" else None,
            "group_id": None if chat_type == "private" else chat_id,
            "attachments": self._translate_attachments(message),
            "transport_address_key": chat_id,
            "transport_address": {
                "provider": "telegram",
                "address_key": chat_id,
                "metadata": {"chat_id": chat_id, "chat_type": chat_type},
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
                provider_message_id=f"telegram:{transport_address.address_key}:{provider_idempotency_key or abs(hash(text))}",
                provider_metadata={"transport_mode": "fake"},
            )
        response = self.client.post(
            f"{account.base_url or f'https://api.telegram.org/bot{account.outbound_token}'}/sendMessage",
            json={
                "chat_id": transport_address.address_key,
                "text": text,
                "reply_to_message_id": self._reply_message_id(reply_to_external_id),
            },
        )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok"):
            raise self._send_error(payload=payload, status_code=response.status_code)
        message = payload.get("result") or {}
        provider_message_id = f"telegram:{transport_address.address_key}:{message.get('message_id')}"
        return SendResult(
            provider_message_id=provider_message_id,
            provider_metadata={"message_id": message.get("message_id"), "transport_mode": "real"},
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
        _ = (mime_type, provider_idempotency_key, session_id)
        if account.mode == "fake":
            prefix = "telegram-voice" if voice else "telegram-media"
            return SendResult(
                provider_message_id=f"{prefix}:{transport_address.address_key}:{abs(hash(storage_key))}",
                provider_metadata={"transport_mode": "fake"},
            )
        method = "sendVoice" if voice else "sendDocument"
        response = self.client.post(
            f"{account.base_url or f'https://api.telegram.org/bot{account.outbound_token}'}/{method}",
            json={
                "chat_id": transport_address.address_key,
                "voice" if voice else "document": storage_key,
                "caption": caption,
                "reply_to_message_id": self._reply_message_id(reply_to_external_id),
            },
        )
        payload = response.json()
        if response.status_code >= 400 or not payload.get("ok"):
            raise self._send_error(payload=payload, status_code=response.status_code)
        message = payload.get("result") or {}
        prefix = "telegram-voice" if voice else "telegram-media"
        return SendResult(
            provider_message_id=f"{prefix}:{transport_address.address_key}:{message.get('message_id')}",
            provider_metadata={"message_id": message.get("message_id"), "transport_mode": "real"},
        )

    def _translate_attachments(self, message: dict[str, Any]) -> list[CanonicalAttachmentInput]:
        attachments: list[CanonicalAttachmentInput] = []
        document = message.get("document")
        voice = message.get("voice")
        if isinstance(document, dict):
            attachments.append(
                CanonicalAttachmentInput(
                    external_attachment_id=str(document.get("file_id") or ""),
                    source_url=f"telegram://file/{document.get('file_id')}",
                    mime_type=str(document.get("mime_type") or "application/octet-stream"),
                    filename=document.get("file_name"),
                    byte_size=document.get("file_size"),
                    provider_metadata={"file_unique_id": document.get("file_unique_id")},
                )
            )
        if isinstance(voice, dict):
            attachments.append(
                CanonicalAttachmentInput(
                    external_attachment_id=str(voice.get("file_id") or ""),
                    source_url=f"telegram://file/{voice.get('file_id')}",
                    mime_type="audio/ogg",
                    filename="voice.ogg",
                    byte_size=voice.get("file_size"),
                    provider_metadata={"duration": voice.get("duration")},
                )
            )
        return attachments

    def _reply_message_id(self, reply_to_external_id: str | None) -> int | None:
        if not reply_to_external_id or not reply_to_external_id.startswith("telegram:"):
            return None
        try:
            return int(reply_to_external_id.rsplit(":", 1)[-1])
        except ValueError:
            return None

    def _send_error(self, *, payload: dict[str, Any], status_code: int) -> ChannelSendError:
        description = str(payload.get("description") or f"http_{status_code}")
        retryable = status_code >= 500 or "Too Many Requests" in description
        if status_code in {401, 403}:
            code = "provider_auth_failed"
        elif "Too Many Requests" in description:
            code = "provider_rate_limited"
        elif retryable:
            code = "provider_unavailable"
        else:
            code = "provider_invalid_request"
        return ChannelSendError(
            error_code=code,
            detail=description,
            retryable=retryable,
            provider_metadata={"status_code": status_code},
        )
