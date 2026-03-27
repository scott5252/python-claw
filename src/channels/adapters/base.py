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
