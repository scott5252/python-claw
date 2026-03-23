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
