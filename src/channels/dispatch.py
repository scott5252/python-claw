from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.channels.adapters.base import ChannelAdapter, ChannelSendError
from src.config.settings import Settings
from src.db.models import ExecutionRunRecord
from src.domain.block_chunker import chunk_text
from src.domain.schemas import DurableTransportAddress
from src.domain.reply_directives import ReplyDirectiveError, parse_reply_directives
from src.observability.failures import classify_failure
from src.observability.logging import build_event, emit_event

logger = logging.getLogger(__name__)


class OutboundDispatchError(RuntimeError):
    pass


@dataclass
class OutboundDispatcher:
    adapters: dict[str, ChannelAdapter]
    settings: Settings

    def dispatch_run(
        self,
        *,
        db: Session,
        repository,
        session,
        execution_run_id: str,
        assistant_text: str,
    ) -> None:
        adapter = self.adapters.get(session.channel_kind)
        if adapter is None:
            return
        account = self.settings.get_channel_account(
            channel_kind=session.channel_kind,
            channel_account_id=session.channel_account_id,
        )
        raw_transport_address = repository.get_session_transport_address(db, session_id=session.id)
        if not raw_transport_address:
            address_key = session.group_id or session.peer_id or session.id
            raw_transport_address = {
                "provider": session.channel_kind,
                "address_key": address_key,
                "metadata": {},
            }
        transport_address = DurableTransportAddress.model_validate(raw_transport_address)
        run = db.get(ExecutionRunRecord, execution_run_id)
        trace_id = run.trace_id if run is not None else None
        artifacts = repository.list_outbound_intents_for_run(
            db,
            session_id=session.id,
            execution_run_id=execution_run_id,
        )
        if not artifacts and assistant_text.strip() and session.channel_kind == "webchat":
            artifacts = [
                repository.append_outbound_intent(
                    db,
                    session_id=session.id,
                    correlation_id=f"assistant:{execution_run_id}",
                    payload={"text": assistant_text, "execution_run_id": execution_run_id},
                )
            ]
        for artifact in artifacts:
            payload = json.loads(artifact.payload_json)
            if self._should_stream_payload(session=session, adapter=adapter, payload=payload):
                self._dispatch_streaming_intent(
                    db=db,
                    repository=repository,
                    session=session,
                    execution_run_id=execution_run_id,
                    trace_id=trace_id,
                    artifact_id=artifact.id,
                    payload=payload,
                    adapter=adapter,
                    account=account,
                    transport_address=transport_address,
                )
                continue
            self._dispatch_intent(
                db=db,
                repository=repository,
                session=session,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                artifact_id=artifact.id,
                payload=payload,
                adapter=adapter,
                account=account,
                transport_address=transport_address,
            )

    def _should_stream_payload(self, *, session, adapter: ChannelAdapter, payload: dict[str, object]) -> bool:
        if session.channel_kind != "webchat":
            return False
        if not self.settings.runtime_streaming_enabled:
            return False
        if not adapter.capabilities.supports_streaming_text:
            return False
        if not self.settings.webchat_sse_enabled:
            return False
        text = str(payload.get("text", ""))
        if not text.strip():
            return False
        try:
            directives = parse_reply_directives(text)
        except ReplyDirectiveError:
            return False
        return not directives.reply_to_external_id and not directives.media_refs and not directives.voice_media_ref

    def _stream_text_chunks(self, *, text: str) -> list[str]:
        size = max(1, self.settings.runtime_streaming_chunk_chars)
        return [text[index : index + size] for index in range(0, len(text), size)] or [text]

    def _dispatch_streaming_intent(
        self,
        *,
        db: Session,
        repository,
        session,
        execution_run_id: str,
        trace_id: str | None,
        artifact_id: int,
        payload: dict[str, object],
        adapter: ChannelAdapter,
        account,
        transport_address: DurableTransportAddress,
    ) -> None:
        text = str(payload.get("text", ""))
        delivery = repository.create_or_get_outbound_delivery(
            db,
            session_id=session.id,
            execution_run_id=execution_run_id,
            trace_id=trace_id,
            outbound_intent_id=artifact_id,
            channel_kind=session.channel_kind,
            channel_account_id=session.channel_account_id,
            delivery_kind="stream_text",
            chunk_index=0,
            chunk_count=1,
            reply_to_external_id=None,
            attachment_id=None,
            delivery_payload={"streaming": True, "text": text},
        )
        if delivery.status == "sent":
            return

        attempt = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=delivery.id,
            trace_id=trace_id,
            provider_idempotency_key=f"{artifact_id}:stream",
            stream_status="pending",
        )
        provider_message_id: str | None = None
        sequence_number = 0
        try:
            begin = adapter.begin_text_stream(
                account=account,
                transport_address=transport_address,
                session_id=session.id,
                provider_idempotency_key=attempt.provider_idempotency_key,
            )
            provider_message_id = begin.provider_message_id
            repository.mark_stream_attempt_state(
                db,
                delivery_id=delivery.id,
                attempt_id=attempt.id,
                attempt_status="started",
                stream_status="streaming",
                provider_message_id=provider_message_id,
                provider_stream_id=begin.provider_metadata.get("stream_id") if isinstance(begin.provider_metadata, dict) else None,
                provider_metadata=begin.provider_metadata,
            )
            db.commit()

            sequence_number += 1
            repository.append_stream_event(
                db,
                delivery_id=delivery.id,
                attempt_id=attempt.id,
                sequence_number=sequence_number,
                event_kind="stream_started",
                payload={"delivery_id": delivery.id},
            )
            db.commit()

            for delta in self._stream_text_chunks(text=text):
                sequence_number += 1
                event = repository.append_stream_event(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    sequence_number=sequence_number,
                    event_kind="text_delta",
                    payload={"text": delta},
                )
                db.commit()
                adapter.append_text_delta(
                    account=account,
                    transport_address=transport_address,
                    session_id=session.id,
                    provider_message_id=provider_message_id,
                    text=delta,
                    sequence_number=event.sequence_number,
                )

            adapter.finalize_text_stream(
                account=account,
                transport_address=transport_address,
                session_id=session.id,
                provider_message_id=provider_message_id,
            )
            sequence_number += 1
            repository.append_stream_event(
                db,
                delivery_id=delivery.id,
                attempt_id=attempt.id,
                sequence_number=sequence_number,
                event_kind="stream_finalized",
                payload={"final_text": text},
            )
            repository.mark_stream_attempt_state(
                db,
                delivery_id=delivery.id,
                attempt_id=attempt.id,
                attempt_status="sent",
                stream_status="finalized",
                completion_reason="completed",
                provider_message_id=provider_message_id,
                provider_metadata={"stream_id": transport_address.address_key, "transport_mode": "sse", "finalized": True},
            )
            db.commit()
        except Exception as exc:
            error_code = "adapter_send_failed"
            retryable = None
            provider_metadata: dict[str, object] | None = None
            if isinstance(exc, ChannelSendError):
                error_code = exc.error_code
                retryable = exc.retryable
                provider_metadata = exc.provider_metadata

            if provider_message_id is not None:
                try:
                    adapter.abort_text_stream(
                        account=account,
                        transport_address=transport_address,
                        session_id=session.id,
                        provider_message_id=provider_message_id,
                        reason=error_code,
                    )
                except Exception:
                    pass

            if repository.delivery_has_stream_text_delta(db, delivery_id=delivery.id):
                repository.mark_stream_attempt_state(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    attempt_status="failed",
                    stream_status="failed",
                    completion_reason="post_first_delta_failure",
                    provider_message_id=provider_message_id,
                    provider_metadata=provider_metadata,
                    error_code=error_code,
                    error_detail=str(exc),
                    retryable=retryable,
                )
                db.commit()
                raise OutboundDispatchError(str(exc)) from exc

            repository.mark_stream_attempt_state(
                db,
                delivery_id=delivery.id,
                attempt_id=attempt.id,
                attempt_status="failed",
                stream_status="failed",
                completion_reason="pre_first_delta_failure",
                provider_message_id=provider_message_id,
                provider_metadata=provider_metadata,
                error_code=error_code,
                error_detail=str(exc),
                retryable=retryable,
            )
            db.commit()
            fallback_attempt = repository.create_outbound_delivery_attempt(
                db,
                outbound_delivery_id=delivery.id,
                trace_id=trace_id,
                provider_idempotency_key=f"{artifact_id}:fallback",
                stream_status="fallback",
            )
            result = adapter.send_text_chunk(
                account=account,
                transport_address=transport_address,
                session_id=session.id,
                text=text,
                reply_to_external_id=None,
                provider_idempotency_key=fallback_attempt.provider_idempotency_key,
            )
            repository.mark_stream_attempt_state(
                db,
                delivery_id=delivery.id,
                attempt_id=fallback_attempt.id,
                attempt_status="sent",
                stream_status="fallback_sent",
                completion_reason="fallback_whole_message",
                provider_message_id=result.provider_message_id,
                provider_metadata=result.provider_metadata,
            )
            db.commit()

    def _dispatch_intent(
        self,
        *,
        db: Session,
        repository,
        session,
        execution_run_id: str,
        trace_id: str | None,
        artifact_id: int,
        payload: dict[str, object],
        adapter: ChannelAdapter,
        account,
        transport_address: DurableTransportAddress,
    ) -> None:
        text = str(payload.get("text", ""))
        try:
            directives = parse_reply_directives(text)
        except ReplyDirectiveError as exc:
            self._record_dispatch_failure(
                db=db,
                repository=repository,
                session=session,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                attachment_id=None,
                error_code="directive_error",
                error_detail=str(exc),
            )
            raise OutboundDispatchError(str(exc)) from exc
        if directives.reply_to_external_id and not adapter.capabilities.supports_reply:
            self._record_dispatch_failure(
                db=db,
                repository=repository,
                session=session,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                attachment_id=None,
                error_code="reply_not_supported",
                error_detail="reply directive unsupported for channel",
            )
            raise OutboundDispatchError("reply directive unsupported for channel")
        if directives.voice_media_ref and not adapter.capabilities.supports_voice:
            self._record_dispatch_failure(
                db=db,
                repository=repository,
                session=session,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                attachment_id=None,
                error_code="voice_not_supported",
                error_detail="voice directive unsupported for channel",
            )
            raise OutboundDispatchError("voice directive unsupported for channel")
        if directives.media_refs and not adapter.capabilities.supports_media:
            self._record_dispatch_failure(
                db=db,
                repository=repository,
                session=session,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                artifact_id=artifact_id,
                chunk_index=0,
                chunk_count=1,
                attachment_id=None,
                error_code="media_not_supported",
                error_detail="media directive unsupported for channel",
            )
            raise OutboundDispatchError("media directive unsupported for channel")

        chunks = chunk_text(text=directives.cleaned_text, max_text_chars=adapter.capabilities.max_text_chars)
        media_refs = directives.media_refs + ([directives.voice_media_ref] if directives.voice_media_ref else [])
        total_count = len(chunks) + len(media_refs)
        for chunk_index, chunk in enumerate(chunks):
            delivery = repository.create_or_get_outbound_delivery(
                db,
                session_id=session.id,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                outbound_intent_id=artifact_id,
                channel_kind=session.channel_kind,
                channel_account_id=session.channel_account_id,
                delivery_kind="text_chunk",
                chunk_index=chunk_index,
                chunk_count=total_count,
                reply_to_external_id=directives.reply_to_external_id,
                attachment_id=None,
                delivery_payload={"text": chunk},
            )
            if delivery.status == "sent":
                continue
            attempt = repository.create_outbound_delivery_attempt(
                db,
                outbound_delivery_id=delivery.id,
                trace_id=trace_id,
                provider_idempotency_key=f"{artifact_id}:{chunk_index}",
            )
            try:
                result = adapter.send_text_chunk(
                    account=account,
                    transport_address=transport_address,
                    session_id=session.id,
                    text=chunk,
                    reply_to_external_id=directives.reply_to_external_id,
                    provider_idempotency_key=attempt.provider_idempotency_key,
                )
                repository.mark_outbound_delivery_sent(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    provider_message_id=result.provider_message_id,
                    provider_metadata=result.provider_metadata,
                )
                self._emit_delivery_event(
                    event_name="delivery.sent",
                    status="sent",
                    trace_id=trace_id,
                    session=session,
                    execution_run_id=execution_run_id,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                )
            except Exception as exc:
                error_code = "adapter_send_failed"
                retryable = None
                provider_metadata: dict[str, object] | None = None
                if isinstance(exc, ChannelSendError):
                    error_code = exc.error_code
                    retryable = exc.retryable
                    provider_metadata = exc.provider_metadata
                repository.mark_outbound_delivery_failed(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    error_code=error_code,
                    error_detail=str(exc),
                    provider_metadata=provider_metadata,
                    retryable=retryable,
                )
                self._emit_delivery_event(
                    event_name="delivery.failed",
                    status="failed",
                    trace_id=trace_id,
                    session=session,
                    execution_run_id=execution_run_id,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    error=str(exc),
                    failure_category=classify_failure(error_code=error_code, exc=exc),
                    level=logging.ERROR,
                )
                raise OutboundDispatchError(str(exc)) from exc

        for media_offset, media_ref in enumerate(media_refs, start=len(chunks)):
            attachment_id = self._resolve_attachment_ref(media_ref)
            attachment = repository.get_message_attachment(db, attachment_id=attachment_id)
            if attachment is None or attachment.normalization_status != "stored" or not attachment.storage_key:
                self._record_dispatch_failure(
                    db=db,
                    repository=repository,
                    session=session,
                    execution_run_id=execution_run_id,
                    trace_id=trace_id,
                    artifact_id=artifact_id,
                    chunk_index=media_offset,
                    chunk_count=total_count,
                    attachment_id=attachment_id,
                    error_code="unknown_media_ref",
                    error_detail=f"unknown media ref: {media_ref}",
                )
                raise OutboundDispatchError(f"unknown media ref: {media_ref}")
            voice = media_ref == directives.voice_media_ref
            if voice and attachment.media_kind != "audio":
                self._record_dispatch_failure(
                    db=db,
                    repository=repository,
                    session=session,
                    execution_run_id=execution_run_id,
                    trace_id=trace_id,
                    artifact_id=artifact_id,
                    chunk_index=media_offset,
                    chunk_count=total_count,
                    attachment_id=attachment_id,
                    error_code="voice_media_invalid",
                    error_detail="voice directive requires audio attachment",
                )
                raise OutboundDispatchError("voice directive requires audio attachment")
            delivery = repository.create_or_get_outbound_delivery(
                db,
                session_id=session.id,
                execution_run_id=execution_run_id,
                trace_id=trace_id,
                outbound_intent_id=artifact_id,
                channel_kind=session.channel_kind,
                channel_account_id=session.channel_account_id,
                delivery_kind="media",
                chunk_index=media_offset,
                chunk_count=total_count,
                reply_to_external_id=directives.reply_to_external_id,
                attachment_id=attachment.id,
                delivery_payload={
                    "storage_key": attachment.storage_key,
                    "mime_type": attachment.mime_type,
                    "voice": voice,
                },
            )
            if delivery.status == "sent":
                continue
            attempt = repository.create_outbound_delivery_attempt(
                db,
                outbound_delivery_id=delivery.id,
                trace_id=trace_id,
                provider_idempotency_key=f"{artifact_id}:{media_offset}",
            )
            try:
                result = adapter.send_media(
                    account=account,
                    transport_address=transport_address,
                    session_id=session.id,
                    storage_key=attachment.storage_key,
                    mime_type=attachment.mime_type,
                    caption=None,
                    voice=voice,
                    reply_to_external_id=directives.reply_to_external_id,
                    provider_idempotency_key=attempt.provider_idempotency_key,
                )
                repository.mark_outbound_delivery_sent(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    provider_message_id=result.provider_message_id,
                    provider_metadata=result.provider_metadata,
                )
                self._emit_delivery_event(
                    event_name="delivery.sent",
                    status="sent",
                    trace_id=trace_id,
                    session=session,
                    execution_run_id=execution_run_id,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                )
            except Exception as exc:
                error_code = "adapter_send_failed"
                retryable = None
                provider_metadata = None
                if isinstance(exc, ChannelSendError):
                    error_code = exc.error_code
                    retryable = exc.retryable
                    provider_metadata = exc.provider_metadata
                repository.mark_outbound_delivery_failed(
                    db,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    error_code=error_code,
                    error_detail=str(exc),
                    provider_metadata=provider_metadata,
                    retryable=retryable,
                )
                self._emit_delivery_event(
                    event_name="delivery.failed",
                    status="failed",
                    trace_id=trace_id,
                    session=session,
                    execution_run_id=execution_run_id,
                    delivery_id=delivery.id,
                    attempt_id=attempt.id,
                    error=str(exc),
                    failure_category=classify_failure(error_code=error_code, exc=exc),
                    level=logging.ERROR,
                )
                raise OutboundDispatchError(str(exc)) from exc

    def _resolve_attachment_ref(self, media_ref: str) -> int:
        raw_value = media_ref.removeprefix("attachment:")
        try:
            return int(raw_value)
        except ValueError as exc:
            raise OutboundDispatchError(f"unsupported media ref: {media_ref}") from exc

    def _record_dispatch_failure(
        self,
        *,
        db: Session,
        repository,
        session,
        execution_run_id: str,
        trace_id: str | None,
        artifact_id: int,
        chunk_index: int,
        chunk_count: int,
        attachment_id: int | None,
        error_code: str,
        error_detail: str,
    ) -> None:
        delivery = repository.create_or_get_outbound_delivery(
            db,
            session_id=session.id,
            execution_run_id=execution_run_id,
            trace_id=trace_id,
            outbound_intent_id=artifact_id,
            channel_kind=session.channel_kind,
            channel_account_id=session.channel_account_id,
            delivery_kind="media" if attachment_id is not None else "text_chunk",
            chunk_index=chunk_index,
            chunk_count=chunk_count,
            reply_to_external_id=None,
            attachment_id=attachment_id,
        )
        attempt = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=delivery.id,
            trace_id=trace_id,
            provider_idempotency_key=f"{artifact_id}:{chunk_index}",
        )
        repository.mark_outbound_delivery_failed(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt.id,
            error_code=error_code,
            error_detail=error_detail,
        )
        self._emit_delivery_event(
            event_name="delivery.failed",
            status="failed",
            trace_id=trace_id,
            session=session,
            execution_run_id=execution_run_id,
            delivery_id=delivery.id,
            attempt_id=attempt.id,
            error=error_detail,
            failure_category=classify_failure(error_code=error_code, error_detail=error_detail),
            level=logging.ERROR,
        )

    def _emit_delivery_event(
        self,
        *,
        event_name: str,
        status: str,
        trace_id: str | None,
        session,
        execution_run_id: str,
        delivery_id: int,
        attempt_id: int,
        level: int = logging.INFO,
        **fields: object,
    ) -> None:
        if self.settings is None:
            return
        emit_event(
            logger,
            level=level,
            event=build_event(
                settings=self.settings,
                event_name=event_name,
                component="dispatcher",
                status=status,
                trace_id=trace_id,
                session_id=session.id,
                execution_run_id=execution_run_id,
                channel_kind=session.channel_kind,
                channel_account_id=session.channel_account_id,
                delivery_id=delivery_id,
                attempt_id=attempt_id,
                **fields,
            ),
        )
