from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.config.settings import Settings
from src.context.outbox import OutboxWorker
from src.context.service import ContextService
from src.db.base import Base
from src.db.models import AttachmentExtractionRecord, OutboxJobRecord
from src.db.session import DatabaseSessionManager
from src.media.extraction import MediaExtractionService
from src.memory.service import MemoryService
from src.retrieval.service import RetrievalService
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


def _append_message(repository: SessionRepository, db, session, *, role: str, content: str, external_id: str):
    return repository.append_message(
        db,
        session,
        role=role,
        content=content,
        external_message_id=external_id,
        sender_id="user-1",
        last_activity_at=datetime.now(timezone.utc),
    )


def test_settings_fail_closed_for_invalid_retrieval_caps() -> None:
    with pytest.raises(ValueError):
        Settings(
            database_url="sqlite://",
            runtime_mode="rule_based",
            retrieval_total_items=4,
            retrieval_memory_items=1,
            retrieval_attachment_items=1,
            retrieval_other_items=1,
        )


def test_memory_provenance_validation_rejects_invalid_source_envelope(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(channel_kind="web", channel_account_id="acct", sender_id="sender", peer_id="peer")
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = _append_message(repository, db, session, role="user", content="remember this", external_id="m1")
        repository.append_summary_snapshot(
            db,
            session_id=session.id,
            base_message_id=message.id,
            through_message_id=message.id,
            source_watermark_message_id=message.id,
            summary_text="summary",
        )
        with pytest.raises(ValueError):
            repository.create_or_get_session_memory(
                db,
                session_id=session.id,
                memory_kind="message_fact",
                content_text="remember this",
                content_hash="abc",
                status="active",
                confidence=0.5,
                source_kind="message",
                source_message_id=None,
                source_summary_snapshot_id=1,
                source_base_message_id=message.id,
                source_through_message_id=message.id,
                derivation_strategy_id="memory-v1",
                payload={},
            )


def test_context_assembly_preserves_transcript_truth_and_uses_summary_when_needed(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(channel_kind="web", channel_account_id="acct", sender_id="sender", peer_id="peer")
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        messages = [
            _append_message(repository, db, session, role="user" if index % 2 else "assistant", content=f"message {index}", external_id=f"m{index}")
            for index in range(1, 7)
        ]
        repository.append_summary_snapshot(
            db,
            session_id=session.id,
            base_message_id=messages[0].id,
            through_message_id=messages[3].id,
            source_watermark_message_id=messages[3].id,
            summary_text="condensed summary",
        )
        state = ContextService(
            context_window=3,
            settings=Settings(database_url="sqlite://", runtime_mode="rule_based", retrieval_enabled=False),
        ).assemble(
            db=db,
            repository=repository,
            session_id=session.id,
            message_id=messages[-1].id,
            agent_id="agent-1",
            channel_kind="web",
            sender_id="user-1",
            user_text="follow up",
        )

    assert state.summary_context is not None
    assert state.summary_context.summary_text == "condensed summary"
    assert [message.content for message in state.messages] == ["message 5", "message 6"]
    assert state.context_manifest["summary_snapshot_ids"]
    assert state.context_manifest["retrieval_ids"] == []
    assert state.context_manifest["memory_ids"] == []


def test_outbox_worker_builds_memory_and_retrieval_from_structured_source_payload(session_manager, tmp_path: Path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(channel_kind="web", channel_account_id="acct", sender_id="sender", peer_id="peer")
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = _append_message(
            repository,
            db,
            session,
            role="user",
            content="Please remember the deployment window is every Tuesday at 9 AM.",
            external_id="m1",
        )
        repository.enqueue_outbox_job(
            db,
            session_id=session.id,
            message_id=message.id,
            job_kind="memory_extraction",
            job_dedupe_key=f"memory_extraction:message:{message.id}",
            payload={"source": {"source_kind": "message", "source_id": message.id, "strategy_id": "memory-v1"}},
        )
        worker = OutboxWorker(
            repository=repository,
            memory_service=MemoryService(strategy_id="memory-v1"),
            retrieval_service=RetrievalService(strategy_id="lexical-v1", chunk_chars=120, min_score=1.0),
        )
        db.commit()

    with session_manager.session() as db:
        completed = worker.run_pending(db, session_id=session.id, now=datetime.now(timezone.utc), limit=10)
        db.commit()

    with session_manager.session() as db:
        completed += worker.run_pending(db, session_id=session.id, now=datetime.now(timezone.utc), limit=10)
        db.commit()

    with session_manager.session() as db:
        memories = repository.list_active_session_memories(db, session_id=session.id)
        retrieval_rows = repository.list_retrieval_records(db, session_id=session.id)

    assert "memory_extraction" in completed
    assert "retrieval_index" in completed
    assert len(memories) == 1
    assert memories[0].source_kind == "message"
    assert retrieval_rows
    assert retrieval_rows[0].source_kind in {"memory", "message"}


def test_same_run_attachment_fast_path_persists_extraction_before_manifest(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    upload = tmp_path / "note.txt"
    upload.write_text("Project codename is cliffside.", encoding="utf-8")

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'spec011.db'}",
        runtime_mode="rule_based",
        media_storage_root=str(media_root),
        diagnostics_admin_bearer_token="admin-secret",
        diagnostics_internal_service_token="internal-secret",
    )
    manager = DatabaseSessionManager(settings.database_url)
    Base.metadata.create_all(manager.engine)
    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    response = client.post(
        "/inbound/message",
        json={
            "channel_kind": "webchat",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "user-1",
            "content": "read the attachment",
            "peer_id": "peer-1",
            "attachments": [
                {
                    "source_url": upload.as_uri(),
                    "mime_type": "text/plain",
                    "filename": "note.txt",
                    "byte_size": upload.stat().st_size,
                    "provider_metadata": {},
                }
            ],
        },
    )
    assert response.status_code == 202

    with manager.session() as db:
        run_id = app.state.run_execution_service.process_next_run(db, worker_id="spec011-worker")
        db.commit()
    assert run_id is not None

    with manager.session() as db:
        repository = SessionRepository()
        extraction = db.query(AttachmentExtractionRecord).one()
        manifests = repository.list_context_manifests(db, session_id=response.json()["session_id"])
        manifest = json.loads(manifests[-1].manifest_json)

    assert extraction.status == "completed"
    assert "cliffside" in (extraction.content_text or "")
    assert manifest["attachment_extraction_ids"] == [extraction.id]
    assert manifest["attachment_fallbacks"] == []


def test_continuity_repair_uses_degraded_assistant_message_for_summary(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'continuity-repair.db'}"
    settings = Settings(
        database_url=database_url,
        runtime_mode="rule_based",
        runtime_transcript_context_limit=2,
        retrieval_enabled=False,
        diagnostics_admin_bearer_token="admin-secret",
        diagnostics_internal_service_token="internal-secret",
    )
    manager = DatabaseSessionManager(settings.database_url)
    Base.metadata.create_all(manager.engine)
    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "webchat",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "user-1",
            "content": "first turn",
            "peer_id": "peer-1",
        },
    )
    assert first.status_code == 202
    with manager.session() as db:
        run_id = app.state.run_execution_service.process_next_run(db, worker_id="spec011-worker")
        db.commit()
    assert run_id is not None

    second = client.post(
        "/inbound/message",
        json={
            "channel_kind": "webchat",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "user-1",
            "content": "second turn",
            "peer_id": "peer-1",
        },
    )
    assert second.status_code == 202
    session_id = second.json()["session_id"]

    with manager.session() as db:
        run_id = app.state.run_execution_service.process_next_run(db, worker_id="spec011-worker")
        db.commit()
    assert run_id is not None
    with manager.session() as db:
        repository = SessionRepository()
        messages = repository.list_messages(db, session_id=session_id, limit=10, before_message_id=None)
        jobs = list(
            db.query(OutboxJobRecord)
            .filter_by(session_id=session_id)
            .order_by(OutboxJobRecord.id.asc())
        )
    degraded_assistant = messages[-1]
    assert degraded_assistant.role == "assistant"
    assert "Continuity repair has been queued." in degraded_assistant.content
    continuity_jobs = [job for job in jobs if job.job_kind == "continuity_repair"]
    assert continuity_jobs
    assert continuity_jobs[-1].message_id == degraded_assistant.id

    worker = OutboxWorker(repository=SessionRepository())
    with manager.session() as db:
        completed = worker.run_pending(db, session_id=session_id, now=datetime.now(timezone.utc), limit=20)
        snapshot = SessionRepository().get_latest_summary_snapshot_for_session(db, session_id=session_id)
        db.commit()

    assert "continuity_repair" in completed
    assert snapshot is not None
    assert snapshot.through_message_id == degraded_assistant.id


def test_attachment_extraction_identity_is_reused_across_retries(session_manager, tmp_path: Path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(channel_kind="web", channel_account_id="acct", sender_id="sender", peer_id="peer")
    )
    upload = tmp_path / "manual.txt"
    upload.write_text("retry-safe extraction", encoding="utf-8")
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = _append_message(repository, db, session, role="user", content="see attachment", external_id="m1")
        inbound = repository.append_inbound_attachments(
            db,
            session_id=session.id,
            message_id=message.id,
            attachments=[
                {
                    "source_url": upload.as_uri(),
                    "mime_type": "text/plain",
                    "filename": "manual.txt",
                    "byte_size": upload.stat().st_size,
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
            source_url=upload.as_uri(),
            storage_key="manual.txt",
            storage_bucket="local",
            mime_type="text/plain",
            media_kind="document",
            filename="manual.txt",
            byte_size=upload.stat().st_size,
            sha256="hash",
            normalization_status="stored",
            retention_expires_at=datetime.now(timezone.utc),
            provider_metadata={},
        )
        (tmp_path / "manual.txt").write_text("retry-safe extraction", encoding="utf-8")
        service = MediaExtractionService(
            storage_root=tmp_path,
            strategy_id="attachment-v1",
            same_run_max_bytes=1024,
            same_run_pdf_page_limit=2,
            same_run_timeout_seconds=1,
        )
        first = service.extract_attachment(db=db, repository=repository, attachment_id=attachment.id, same_run=False)
        second = service.extract_attachment(db=db, repository=repository, attachment_id=attachment.id, same_run=False)

    assert first.id == second.id
