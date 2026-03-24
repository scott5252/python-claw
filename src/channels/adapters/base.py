from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelCapabilities:
    max_text_chars: int
    supports_reply: bool
    supports_media: bool
    supports_voice: bool


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str


class ChannelAdapter:
    channel_kind: str
    capabilities: ChannelCapabilities

    def send_text_chunk(
        self,
        *,
        channel_account_id: str,
        session_id: str,
        text: str,
        reply_to_external_id: str | None,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        raise NotImplementedError

    def send_media(
        self,
        *,
        channel_account_id: str,
        session_id: str,
        storage_key: str,
        mime_type: str,
        caption: str | None,
        voice: bool,
        reply_to_external_id: str | None,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        raise NotImplementedError
