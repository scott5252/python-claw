from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.db.models import ExecutionRunRecord
from src.channels.adapters.telegram import TelegramAdapter
from src.channels.adapters.webchat import WebchatAdapter
from src.channels.dispatch import OutboundDispatchError, OutboundDispatcher
from src.domain.block_chunker import chunk_text
from src.domain.reply_directives import ReplyDirectiveError, parse_reply_directives
from src.media.processor import AttachmentNormalizationRetryableError, MediaProcessor
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


def test_parse_reply_directives_strips_supported_directives() -> None:
    parsed = parse_reply_directives("Hello [[reply:ext-1]] world [[media:attachment:7]] [[voice:attachment:8]]")
    assert parsed.cleaned_text.replace("  ", " ") == "Hello world"
    assert parsed.reply_to_external_id == "ext-1"
    assert parsed.media_refs == ["attachment:7"]
    assert parsed.voice_media_ref == "attachment:8"


def test_parse_reply_directives_rejects_malformed_text() -> None:
    with pytest.raises(ReplyDirectiveError):
        parse_reply_directives("Hello [[reply]]")


def test_chunk_text_prefers_paragraphs_and_hard_splits_long_blocks() -> None:
    chunks = chunk_text(text="one\n\ntwo\n\nabcdefghij", max_text_chars=6)
    assert chunks == ["one", "two", "abcdef", "ghij"]


def test_media_processor_stores_safe_attachment_and_rejects_invalid_mime(session_manager, tmp_path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="slack",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )
    source_path = tmp_path / "safe.txt"
    source_path.write_text("hello media")

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        repository.append_inbound_attachments(
            db,
            session_id=session.id,
            message_id=message.id,
            attachments=[
                {
                    "source_url": source_path.resolve().as_uri(),
                    "mime_type": "text/plain",
                    "provider_metadata": {"provider": "test"},
                },
                {
                    "source_url": source_path.resolve().as_uri(),
                    "mime_type": "video/mp4",
                    "provider_metadata": {"provider": "test"},
                },
            ],
        )
        processor = MediaProcessor(
            storage_root=Path(tmp_path / "media-store"),
            storage_bucket="test-bucket",
            retention_days=30,
            max_bytes=1024,
            allowed_schemes=("file",),
            allowed_mime_prefixes=("text/", "image/", "audio/", "application/pdf"),
        )
        stored_ids = processor.normalize_message_attachments(
            db=db,
            repository=repository,
            session_id=session.id,
            message_id=message.id,
        )
        db.commit()

    with session_manager.session() as db:
        rows = repository.list_message_attachments_for_message(db, message_id=message.id)

    assert len(stored_ids) == 1
    assert rows[0].normalization_status == "stored"
    assert rows[0].storage_key is not None
    assert json.loads(rows[0].provider_metadata_json) == {"provider": "test"}
    assert rows[1].normalization_status == "rejected"


def test_media_processor_records_retryable_failure(session_manager, tmp_path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="slack",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )
    missing_uri = (tmp_path / "missing.txt").resolve().as_uri()

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        inbound = repository.append_inbound_attachments(
            db,
            session_id=session.id,
            message_id=message.id,
            attachments=[{"source_url": missing_uri, "mime_type": "text/plain", "provider_metadata": {}}],
        )[0]
        processor = MediaProcessor(
            storage_root=Path(tmp_path / "media-store"),
            storage_bucket="test-bucket",
            retention_days=30,
            max_bytes=1024,
            allowed_schemes=("file",),
            allowed_mime_prefixes=("text/",),
        )
        with pytest.raises(AttachmentNormalizationRetryableError):
            processor.normalize_message_attachments(
                db=db,
                repository=repository,
                session_id=session.id,
                message_id=message.id,
            )
        latest = repository.get_latest_message_attachment_for_inbound(
            db,
            inbound_message_attachment_id=inbound.id,
        )

    assert latest is not None
    assert latest.normalization_status == "failed"


def test_dispatcher_chunks_text_and_fails_closed_for_unsupported_voice(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="webchat",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        db.add(
            ExecutionRunRecord(
                id="run-1",
                session_id=session.id,
                message_id=None,
                agent_id="agent-1",
                trigger_kind="test",
                trigger_ref="test-1",
                lane_key=session.id,
                status="queued",
                attempt_count=0,
                max_attempts=1,
                available_at=datetime.now(timezone.utc),
                trace_id="trace-1",
                correlation_id="trace-1",
            )
        )
        artifact = repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-1",
            payload={
                "text": "para one\n\npara two [[voice:attachment:9]]",
                "execution_run_id": "run-1",
            },
        )
        dispatcher = OutboundDispatcher(adapters={"webchat": WebchatAdapter()}, settings=Settings(database_url="sqlite://"))
        with pytest.raises(OutboundDispatchError):
            dispatcher.dispatch_run(
                db=db,
                repository=repository,
                session=session,
                execution_run_id="run-1",
                assistant_text="Prepared outbound message",
            )
        deliveries = repository.list_outbound_deliveries(db, session_id=session.id)
        attempts = repository.list_outbound_delivery_attempts(db, delivery_id=deliveries[0].id)

    assert artifact.id == deliveries[0].outbound_intent_id
    assert deliveries[0].status == "failed"
    assert deliveries[0].trace_id == "trace-1"
    assert attempts[0].status == "failed"


def test_dispatcher_sends_chunked_text_and_media(session_manager, tmp_path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="telegram",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        db.add(
            ExecutionRunRecord(
                id="run-1",
                session_id=session.id,
                message_id=None,
                agent_id="agent-1",
                trigger_kind="test",
                trigger_ref="test-1",
                lane_key=session.id,
                status="queued",
                attempt_count=0,
                max_attempts=1,
                available_at=datetime.now(timezone.utc),
                trace_id="trace-1",
                correlation_id="trace-1",
            )
        )
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        inbound = repository.append_inbound_attachments(
            db,
            session_id=session.id,
            message_id=message.id,
            attachments=[
                {
                    "source_url": (tmp_path / "voice.ogg").resolve().as_uri(),
                    "mime_type": "audio/ogg",
                    "provider_metadata": {},
                }
            ],
        )[0]
        attachment = repository.append_message_attachment(
            db,
            inbound_attachment_id=inbound.id,
            message_id=message.id,
            session_id=session.id,
            ordinal=0,
            external_attachment_id=None,
            source_url=(tmp_path / "voice.ogg").resolve().as_uri(),
            storage_key="telegram/voice.ogg",
            storage_bucket="test",
            mime_type="audio/ogg",
            media_kind="audio",
            filename="voice.ogg",
            byte_size=8,
            sha256="abc",
            normalization_status="stored",
            retention_expires_at=None,
            provider_metadata={},
        )
        repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-1",
            payload={
                "text": "first paragraph\n\nsecond paragraph [[reply:ext-1]] [[voice:attachment:%d]]" % attachment.id,
                "execution_run_id": "run-1",
            },
        )
        dispatcher = OutboundDispatcher(adapters={"telegram": TelegramAdapter()}, settings=Settings(database_url="sqlite://"))
        dispatcher.dispatch_run(
            db=db,
            repository=repository,
            session=session,
            execution_run_id="run-1",
            assistant_text="Prepared outbound message",
        )
        deliveries = repository.list_outbound_deliveries(db, session_id=session.id)

    assert [delivery.delivery_kind for delivery in deliveries] == ["text_chunk", "media"]
    assert all(delivery.status == "sent" for delivery in deliveries)
    assert all(delivery.trace_id == "trace-1" for delivery in deliveries)
