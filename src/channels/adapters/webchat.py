from __future__ import annotations

from src.channels.adapters.base import ChannelAdapter, ChannelCapabilities, SendResult
from src.config.settings import ChannelAccountConfig
from src.domain.schemas import DurableTransportAddress


class WebchatAdapter(ChannelAdapter):
    channel_kind = "webchat"
    capabilities = ChannelCapabilities(
        max_text_chars=4000,
        supports_reply=False,
        supports_media=True,
        supports_voice=False,
        supports_streaming_text=True,
        supports_stream_finalize=True,
        supports_stream_abort=True,
    )

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
        _ = (account, session_id, text, reply_to_external_id)
        return SendResult(
            provider_message_id=f"webchat:{transport_address.address_key}:{provider_idempotency_key or 'message'}",
            provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "poll"},
        )

    def begin_text_stream(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        _ = (account, session_id)
        provider_message_id = f"webchat-stream:{transport_address.address_key}:{provider_idempotency_key or 'stream'}"
        return SendResult(
            provider_message_id=provider_message_id,
            provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "sse"},
        )

    def append_text_delta(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_message_id: str,
        text: str,
        sequence_number: int,
    ) -> SendResult:
        _ = (account, session_id, text, sequence_number)
        return SendResult(
            provider_message_id=provider_message_id,
            provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "sse"},
        )

    def finalize_text_stream(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_message_id: str,
    ) -> SendResult:
        _ = (account, session_id)
        return SendResult(
            provider_message_id=provider_message_id,
            provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "sse", "finalized": True},
        )

    def abort_text_stream(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_message_id: str,
        reason: str,
    ) -> SendResult:
        _ = (account, session_id, reason)
        return SendResult(
            provider_message_id=provider_message_id,
            provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "sse", "aborted": True},
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
        _ = (account, session_id, mime_type, caption, voice, reply_to_external_id)
        return SendResult(
            provider_message_id=f"webchat-media:{transport_address.address_key}:{provider_idempotency_key or storage_key}",
            provider_metadata={"stream_id": transport_address.address_key, "storage_key": storage_key, "transport_mode": "poll"},
        )
