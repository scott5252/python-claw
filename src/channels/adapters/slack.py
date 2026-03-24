from __future__ import annotations

from src.channels.adapters.base import ChannelAdapter, ChannelCapabilities, SendResult


class SlackAdapter(ChannelAdapter):
    channel_kind = "slack"
    capabilities = ChannelCapabilities(
        max_text_chars=3000,
        supports_reply=True,
        supports_media=True,
        supports_voice=False,
    )

    def send_text_chunk(self, *, channel_account_id: str, session_id: str, text: str, reply_to_external_id: str | None, provider_idempotency_key: str | None) -> SendResult:
        _ = (channel_account_id, session_id, reply_to_external_id, provider_idempotency_key)
        return SendResult(provider_message_id=f"slack:{abs(hash(text))}")

    def send_media(self, *, channel_account_id: str, session_id: str, storage_key: str, mime_type: str, caption: str | None, voice: bool, reply_to_external_id: str | None, provider_idempotency_key: str | None) -> SendResult:
        _ = (channel_account_id, session_id, mime_type, caption, voice, reply_to_external_id, provider_idempotency_key)
        return SendResult(provider_message_id=f"slack-media:{abs(hash(storage_key))}")
