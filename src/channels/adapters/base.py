from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.config.settings import ChannelAccountConfig
from src.domain.schemas import DurableTransportAddress


@dataclass(frozen=True)
class ChannelCapabilities:
    max_text_chars: int
    supports_reply: bool
    supports_media: bool
    supports_voice: bool
    supports_streaming_text: bool = False
    supports_stream_finalize: bool = False
    supports_stream_abort: bool = False


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class ChannelSendError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        detail: str,
        retryable: bool,
        provider_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        self.provider_metadata = provider_metadata or {}


class ChannelAdapter:
    channel_kind: str
    capabilities: ChannelCapabilities

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
        raise NotImplementedError

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
        raise NotImplementedError

    def begin_text_stream(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_idempotency_key: str | None,
    ) -> SendResult:
        raise ChannelSendError(
            error_code="streaming_not_supported",
            detail="streaming not supported for channel",
            retryable=False,
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
        raise ChannelSendError(
            error_code="streaming_not_supported",
            detail="streaming not supported for channel",
            retryable=False,
        )

    def finalize_text_stream(
        self,
        *,
        account: ChannelAccountConfig,
        transport_address: DurableTransportAddress,
        session_id: str,
        provider_message_id: str,
    ) -> SendResult:
        raise ChannelSendError(
            error_code="stream_finalize_not_supported",
            detail="stream finalize not supported for channel",
            retryable=False,
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
        raise ChannelSendError(
            error_code="stream_abort_not_supported",
            detail="stream abort not supported for channel",
            retryable=False,
        )
