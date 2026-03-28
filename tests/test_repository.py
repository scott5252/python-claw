from __future__ import annotations

import json
from datetime import datetime, timezone

from src.context.outbox import OutboxWorker
from src.db.models import ActiveResourceRecord, ResourceApprovalRecord
from src.graphs.state import ToolEvent, ToolRequest
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


def test_get_or_create_session_reuses_canonical_key(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        first = repository.get_or_create_session(db, routing)
        db.commit()

    with session_manager.session() as db:
        second = repository.get_or_create_session(db, routing)
        assert first.id == second.id


def test_message_paging_is_append_ordered(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        first = repository.append_message(
            db,
            session,
            role="user",
            content="one",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        second = repository.append_message(
            db,
            session,
            role="user",
            content="two",
            external_message_id="m2",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        third = repository.append_message(
            db,
            session,
            role="user",
            content="three",
            external_message_id="m3",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        db.commit()

    with session_manager.session() as db:
        page = repository.list_messages(db, session_id=session.id, limit=2, before_message_id=None)
        assert [row.id for row in page] == [second.id, third.id]

        next_page = repository.list_messages(db, session_id=session.id, limit=2, before_message_id=second.id)
        assert [row.id for row in next_page] == [first.id]


def test_append_only_runtime_artifacts_are_persisted_in_order(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        repository.append_tool_proposal(
            db,
            session_id=session.id,
            request=ToolRequest(
                correlation_id="corr-1",
                capability_name="echo_text",
                arguments={"text": "hello"},
            ),
        )
        repository.append_tool_event(
            db,
            session_id=session.id,
            event=ToolEvent(
                correlation_id="corr-1",
                capability_name="echo_text",
                status="succeeded",
                arguments={"text": "hello"},
                outcome={"content": "hello"},
            ),
        )
        repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-2",
            payload={"text": "ship it", "channel_kind": "web", "sender_id": "sender"},
        )
        db.commit()

    with session_manager.session() as db:
        artifacts = repository.list_artifacts(db, session_id=session.id)
        assert [artifact.artifact_kind for artifact in artifacts] == [
            "tool_proposal",
            "tool_result",
            "outbound_intent",
        ]
        assert json.loads(artifacts[0].payload_json) == {"arguments": {"text": "hello"}}
        assert json.loads(artifacts[1].payload_json) == {
            "arguments": {"text": "hello"},
            "outcome": {"content": "hello"},
        }
        assert json.loads(artifacts[2].payload_json)["text"] == "ship it"


def test_summary_snapshots_select_latest_valid_version_and_manifest_retention(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        messages = [
            repository.append_message(
                db,
                session,
                role="user" if index % 2 == 0 else "assistant",
                content=f"m{index}",
                external_message_id=f"m{index}",
                sender_id="sender",
                last_activity_at=datetime.now(timezone.utc),
            )
            for index in range(1, 7)
        ]
        older = repository.append_summary_snapshot(
            db,
            session_id=session.id,
            base_message_id=messages[0].id,
            through_message_id=messages[2].id,
            source_watermark_message_id=messages[2].id,
            summary_text="older",
        )
        newer = repository.append_summary_snapshot(
            db,
            session_id=session.id,
            base_message_id=messages[0].id,
            through_message_id=messages[3].id,
            source_watermark_message_id=messages[3].id,
            summary_text="newer",
        )
        repository.append_context_manifest(
            db,
            session_id=session.id,
            message_id=messages[3].id,
            manifest={"turn": 1},
            degraded=False,
            retention_limit=2,
        )
        repository.append_context_manifest(
            db,
            session_id=session.id,
            message_id=messages[4].id,
            manifest={"turn": 2},
            degraded=False,
            retention_limit=2,
        )
        repository.append_context_manifest(
            db,
            session_id=session.id,
            message_id=messages[5].id,
            manifest={"turn": 3},
            degraded=True,
            retention_limit=2,
        )
        db.commit()

    with session_manager.session() as db:
        selected = repository.get_latest_valid_summary_snapshot(
            db,
            session_id=session.id,
            message_id=messages[5].id,
        )
        manifests = repository.list_context_manifests(db, session_id=session.id)

    assert selected is not None
    assert selected.id == newer.id
    assert selected.id != older.id
    assert [json.loads(item.manifest_json)["turn"] for item in manifests] == [2, 3]
    assert manifests[-1].degraded is True


def test_duplicate_outbox_jobs_and_governance_replay_are_idempotent(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        prompt = repository.append_message(
            db,
            session,
            role="user",
            content="send hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        proposal, version = repository.create_governance_proposal(
            db,
            session_id=session.id,
            message_id=prompt.id,
            agent_id="agent-1",
            requested_by="sender",
            capability_name="send_message",
            arguments={"text": "hello"},
        )
        approval_message = repository.append_message(
            db,
            session,
            role="user",
            content=f"approve {proposal.id}",
            external_message_id="m2",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        approval = repository.approve_proposal(
            db,
            session_id=session.id,
            message_id=approval_message.id,
            proposal_id=proposal.id,
            approver_id="sender",
        )
        active, _ = repository.activate_approved_resource(
            db,
            proposal_id=proposal.id,
            resource_version_id=version.id,
            typed_action_id=approval.typed_action_id,
            canonical_params_hash=approval.canonical_params_hash,
        )
        repository.append_governance_event(
            db,
            session_id=session.id,
            message_id=approval_message.id,
            event_kind="activation_result",
            proposal_id=proposal.id,
            resource_version_id=version.id,
            active_resource_id=active.id,
            payload={"activation_state": "active"},
        )
        first = repository.enqueue_outbox_job(
            db,
            session_id=session.id,
            message_id=approval_message.id,
            job_kind="summary_generation",
            job_dedupe_key="summary:1",
        )
        second = repository.enqueue_outbox_job(
            db,
            session_id=session.id,
            message_id=approval_message.id,
            job_kind="summary_generation",
            job_dedupe_key="summary:1",
        )
        db.commit()

    with session_manager.session() as db:
        jobs = repository.claim_outbox_jobs(db, session_id=session.id, now=datetime.now(timezone.utc), limit=5)
        repository.complete_outbox_job(db, job_id=jobs[0].id)
        db.query(ResourceApprovalRecord).delete()
        db.query(ActiveResourceRecord).delete()
        replayed = repository.replay_active_approvals(
            db,
            session_id=session.id,
            agent_id="agent-1",
            now=datetime.now(timezone.utc),
        )
        db.commit()

    assert first.id == second.id
    assert len(jobs) == 1
    assert replayed[0]["proposal_id"] == proposal.id
    assert replayed[0]["active_resource_id"] == active.id


def test_outbox_worker_generates_additive_summary_snapshots(session_manager) -> None:
    repository = SessionRepository()
    worker = OutboxWorker(repository=repository)
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        for index in range(1, 6):
            repository.append_message(
                db,
                session,
                role="user" if index % 2 else "assistant",
                content=f"turn-{index}",
                external_message_id=f"m{index}",
                sender_id="sender",
                last_activity_at=datetime.now(timezone.utc),
            )
        repository.enqueue_outbox_job(
            db,
            session_id=session.id,
            message_id=5,
            job_kind="summary_generation",
            job_dedupe_key=f"summary_generation:{session.id}:5",
        )
        db.commit()

    with session_manager.session() as db:
        completed = worker.run_pending(db, session_id=session.id, now=datetime.now(timezone.utc))
        snapshot = repository.get_latest_valid_summary_snapshot(db, session_id=session.id, message_id=6)
        db.commit()

    assert completed == ["summary_generation"]
    assert snapshot is not None
    assert snapshot.base_message_id == 1
    assert snapshot.through_message_id == 5


def test_attachment_and_delivery_records_are_append_only_and_chunk_idempotent(session_manager, tmp_path) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="slack",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

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
            attachments=[
                {
                    "source_url": (tmp_path / "a.txt").resolve().as_uri(),
                    "mime_type": "text/plain",
                    "provider_metadata": {"source": "test"},
                }
            ],
        )[0]
        failed = repository.append_message_attachment(
            db,
            inbound_attachment_id=inbound.id,
            message_id=message.id,
            session_id=session.id,
            ordinal=0,
            external_attachment_id=None,
            source_url=inbound.source_url,
            storage_key=None,
            storage_bucket=None,
            mime_type=inbound.mime_type,
            media_kind="document",
            filename=None,
            byte_size=None,
            sha256=None,
            normalization_status="failed",
            retention_expires_at=None,
            provider_metadata={"source": "test"},
            error_detail="temporary failure",
        )
        stored = repository.append_message_attachment(
            db,
            inbound_attachment_id=inbound.id,
            message_id=message.id,
            session_id=session.id,
            ordinal=0,
            external_attachment_id=None,
            source_url=inbound.source_url,
            storage_key="session/message/file.txt",
            storage_bucket="bucket",
            mime_type=inbound.mime_type,
            media_kind="document",
            filename="a.txt",
            byte_size=12,
            sha256="abc123",
            normalization_status="stored",
            retention_expires_at=datetime.now(timezone.utc),
            provider_metadata={"source": "test"},
        )
        artifact = repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-1",
            payload={"text": "hello", "execution_run_id": "run-1"},
        )
        first_delivery = repository.create_or_get_outbound_delivery(
            db,
            session_id=session.id,
            execution_run_id="run-1",
            trace_id="trace-1",
            outbound_intent_id=artifact.id,
            channel_kind="slack",
            channel_account_id="acct",
            delivery_kind="text_chunk",
            chunk_index=0,
            chunk_count=2,
            reply_to_external_id=None,
            attachment_id=None,
        )
        same_delivery = repository.create_or_get_outbound_delivery(
            db,
            session_id=session.id,
            execution_run_id="run-1",
            trace_id="trace-1",
            outbound_intent_id=artifact.id,
            channel_kind="slack",
            channel_account_id="acct",
            delivery_kind="text_chunk",
            chunk_index=0,
            chunk_count=2,
            reply_to_external_id=None,
            attachment_id=None,
        )
        attempt_one = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=first_delivery.id,
            trace_id="trace-1",
            provider_idempotency_key="key-1",
        )
        repository.mark_outbound_delivery_failed(
            db,
            delivery_id=first_delivery.id,
            attempt_id=attempt_one.id,
            error_code="send_failed",
            error_detail="network issue",
        )
        attempt_two = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=first_delivery.id,
            trace_id="trace-1",
            provider_idempotency_key="key-2",
        )
        repository.mark_outbound_delivery_sent(
            db,
            delivery_id=first_delivery.id,
            attempt_id=attempt_two.id,
            provider_message_id="provider-1",
        )
        db.commit()

    with session_manager.session() as db:
        latest = repository.get_latest_message_attachment_for_inbound(
            db,
            inbound_message_attachment_id=inbound.id,
        )
        stored_rows = repository.list_stored_message_attachments_for_message(db, message_id=message.id)
        deliveries = repository.list_outbound_deliveries(db, session_id=session.id)
        attempts = repository.list_outbound_delivery_attempts(db, delivery_id=first_delivery.id)

    assert failed.id != stored.id
    assert latest is not None
    assert latest.id == stored.id
    assert [row.id for row in stored_rows] == [stored.id]
    assert first_delivery.id == same_delivery.id
    assert len(deliveries) == 1
    assert deliveries[0].status == "sent"
    assert deliveries[0].trace_id == "trace-1"
    assert len(attempts) == 2
    assert attempts[0].status == "failed"
    assert attempts[1].status == "sent"
    assert attempts[0].trace_id == "trace-1"


def test_stream_delivery_events_are_append_only_and_reconstruct_text(session_manager) -> None:
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
        artifact = repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-stream",
            payload={"text": "hello streamed world", "execution_run_id": "run-1"},
        )
        delivery = repository.create_or_get_outbound_delivery(
            db,
            session_id=session.id,
            execution_run_id="run-1",
            trace_id="trace-1",
            outbound_intent_id=artifact.id,
            channel_kind="webchat",
            channel_account_id="acct",
            delivery_kind="stream_text",
            chunk_index=0,
            chunk_count=1,
            reply_to_external_id=None,
            attachment_id=None,
            delivery_payload={"streaming": True},
        )
        attempt_one = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=delivery.id,
            trace_id="trace-1",
            provider_idempotency_key="stream-1",
            stream_status="pending",
        )
        repository.append_stream_event(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_one.id,
            sequence_number=1,
            event_kind="stream_started",
            payload={},
        )
        repository.append_stream_event(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_one.id,
            sequence_number=2,
            event_kind="text_delta",
            payload={"text": "hello "},
        )
        repository.append_stream_event(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_one.id,
            sequence_number=3,
            event_kind="text_delta",
            payload={"text": "streamed"},
        )
        repository.mark_stream_attempt_state(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_one.id,
            attempt_status="failed",
            stream_status="failed",
            completion_reason="interrupted",
            error_code="transport_closed",
            error_detail="transport closed",
            retryable=True,
        )
        attempt_two = repository.create_outbound_delivery_attempt(
            db,
            outbound_delivery_id=delivery.id,
            trace_id="trace-1",
            provider_idempotency_key="stream-2",
            stream_status="pending",
        )
        repository.append_stream_event(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_two.id,
            sequence_number=1,
            event_kind="stream_started",
            payload={},
        )
        repository.append_stream_event(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_two.id,
            sequence_number=2,
            event_kind="text_delta",
            payload={"text": "hello streamed world"},
        )
        repository.mark_stream_attempt_state(
            db,
            delivery_id=delivery.id,
            attempt_id=attempt_two.id,
            attempt_status="sent",
            stream_status="finalized",
            completion_reason="completed",
            provider_message_id="provider-1",
            provider_metadata={"stream_id": "peer"},
        )
        db.commit()

    with session_manager.session() as db:
        events = repository.list_delivery_stream_events(db, delivery_id=delivery.id)
        attempts = repository.list_outbound_delivery_attempts(db, delivery_id=delivery.id)
        reconstructed = repository.stream_text_for_attempt(db, attempt_id=attempt_two.id)

    assert delivery.id == attempts[0].outbound_delivery_id == attempts[1].outbound_delivery_id
    assert [event.sequence_number for event in events if event.outbound_delivery_attempt_id == attempt_one.id] == [1, 2, 3]
    assert reconstructed == "hello streamed world"
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
