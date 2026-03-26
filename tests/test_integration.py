from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.capabilities.activation import ActivationController
from src.config.settings import Settings
from src.context.service import ContextService
from src.db.base import Base
from src.db.models import (
    ActiveResourceRecord,
    ContextManifestRecord,
    DedupeStatus,
    ExecutionRunRecord,
    ExecutionRunStatus,
    GlobalRunLeaseRecord,
    GovernanceTranscriptEventRecord,
    InboundDedupeRecord,
    MessageAttachmentRecord,
    OutboxJobRecord,
    OutboundDeliveryRecord,
    ResourceApprovalRecord,
    ResourceProposalRecord,
    ScheduledJobFireRecord,
    ScheduledJobRecord,
    SessionArtifactRecord,
    ToolAuditEventRecord,
)
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.graphs.state import AssistantState, ModelTurnResult, ToolRequest
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService, SchedulerService
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService
from src.providers.models import ModelAdapter
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService
from src.tools.local_safe import create_echo_text_tool
from src.tools.messaging import create_send_message_tool
from src.tools.registry import ToolDefinition, ToolRegistry


@dataclass
class StaticModel(ModelAdapter):
    result: ModelTurnResult

    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        _ = state
        _ = available_tools
        return self.result


def build_session_service(
    *,
    model: ModelAdapter,
    policy_service: PolicyService | None = None,
    tool_registry: ToolRegistry | None = None,
) -> SessionService:
    repository = SessionRepository()
    graph = GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=policy_service or PolicyService(),
            model=model,
            tool_registry=tool_registry
            or ToolRegistry(
                factories={
                    "echo_text": create_echo_text_tool,
                    "send_message": create_send_message_tool,
                }
            ),
            audit_sink=ToolAuditSink(),
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(context_window=10),
        )
    ).build()
    return SessionService(
        repository=repository,
        jobs_repository=JobsRepository(),
        idempotency_service=IdempotencyService(),
        default_agent_id="agent-1",
        dedupe_retention_days=30,
        dedupe_stale_after_seconds=1,
        messages_page_default_limit=2,
        messages_page_max_limit=5,
        session_runs_page_default_limit=5,
        session_runs_page_max_limit=10,
        execution_run_max_attempts=5,
    )


def build_run_execution_service(
    *,
    model: ModelAdapter,
    policy_service: PolicyService | None = None,
    tool_registry: ToolRegistry | None = None,
) -> RunExecutionService:
    repository = SessionRepository()

    def assistant_graph_factory():
        return GraphFactory(
            GraphDependencies(
                repository=repository,
                policy_service=policy_service or PolicyService(),
                model=model,
                tool_registry=tool_registry
                or ToolRegistry(
                    factories={
                        "echo_text": create_echo_text_tool,
                        "send_message": create_send_message_tool,
                    }
                ),
                audit_sink=ToolAuditSink(),
                activation_controller=ActivationController(repository=repository),
                context_service=ContextService(context_window=10),
            )
        ).build()

    jobs_repository = JobsRepository()
    return RunExecutionService(
        jobs_repository=jobs_repository,
        session_repository=repository,
        concurrency_service=SessionConcurrencyService(
            repository=jobs_repository,
            lease_seconds=60,
            global_concurrency_limit=4,
        ),
        assistant_graph_factory=assistant_graph_factory,
        failure_classifier=FailureClassifier(),
        base_backoff_seconds=1,
        max_backoff_seconds=5,
    )


def drain_queue(manager: DatabaseSessionManager, execution_service: RunExecutionService, *, max_runs: int = 20) -> list[str]:
    processed: list[str] = []
    for _ in range(max_runs):
        with manager.session() as db:
            run_id = execution_service.process_next_run(db, worker_id="integration-worker")
            db.commit()
        if run_id is None:
            break
        processed.append(run_id)
    return processed


def test_restart_safe_session_reuse_and_duplicate_replay(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    settings = Settings(
        database_url=database_url,
        runtime_mode="rule_based",
        dedupe_stale_after_seconds=1,
        messages_page_default_limit=2,
        messages_page_max_limit=3,
    )
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app1 = create_app(settings=settings, session_manager=manager)
    client1 = TestClient(app1)
    first = client1.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    session_id = first.json()["session_id"]
    drain_queue(manager, app1.state.run_execution_service)
    message_id = first.json()["message_id"]

    manager2 = DatabaseSessionManager(database_url)
    app2 = create_app(settings=settings, session_manager=manager2)
    client2 = TestClient(app2)

    duplicate = client2.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    assert duplicate.json()["session_id"] == session_id
    assert duplicate.json()["message_id"] == message_id

    next_message = client2.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "follow-up",
            "peer_id": "peer",
        },
    )
    assert next_message.json()["session_id"] == session_id


def test_stale_claimed_recovery_and_history_paging(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based", dedupe_stale_after_seconds=1)
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    with manager.session() as db:
        db.add(
            InboundDedupeRecord(
                status=DedupeStatus.CLAIMED.value,
                channel_kind="slack",
                channel_account_id="acct",
                external_message_id="msg-stale",
                first_seen_at=datetime.now(timezone.utc) - timedelta(seconds=120),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        db.commit()

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    recovered = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-stale",
            "sender_id": "sender",
            "content": "one",
            "peer_id": "peer",
        },
    )
    assert recovered.status_code == 202
    session_id = recovered.json()["session_id"]

    client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "two",
            "peer_id": "peer",
        },
    )
    client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-3",
            "sender_id": "sender",
            "content": "three",
            "peer_id": "peer",
        },
    )
    drain_queue(manager, app.state.run_execution_service)

    page_one = client.get(f"/sessions/{session_id}/messages", params={"limit": 2})
    body_one = page_one.json()
    assert body_one["items"][-1]["content"] == "Received: three"
    assert any(item["content"] == "three" for item in body_one["items"] + client.get(
        f"/sessions/{session_id}/messages",
        params={"limit": 4},
    ).json()["items"])
    assert body_one["next_before_message_id"] == 5

    page_two = client.get(
        f"/sessions/{session_id}/messages",
        params={"limit": 2, "before_message_id": 5},
    )
    body_two = page_two.json()
    assert len(body_two["items"]) == 2
    assert any(item["content"] == "Received: one" for item in body_two["items"])


def test_unapproved_tool_request_creates_governance_proposal_without_tool_artifact(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'unapproved.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    app.state.session_service = build_session_service(
        model=StaticModel(
            ModelTurnResult(
                needs_tools=True,
                tool_requests=[
                    ToolRequest(
                        correlation_id="corr-1",
                        capability_name="send_message",
                        arguments={"text": "hello channel"},
                    )
                ],
                response_text="",
            )
        ),
        tool_registry=ToolRegistry(factories={"send_message": create_send_message_tool}),
    )
    app.state.run_execution_service = build_run_execution_service(
        model=StaticModel(
            ModelTurnResult(
                needs_tools=True,
                tool_requests=[
                    ToolRequest(
                        correlation_id="corr-1",
                        capability_name="send_message",
                        arguments={"text": "hello channel"},
                    )
                ],
                response_text="",
            )
        ),
        tool_registry=ToolRegistry(factories={"send_message": create_send_message_tool}),
    )
    client = TestClient(app)

    response = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "do the thing",
            "peer_id": "peer",
        },
    )
    assert response.status_code == 202
    session_id = response.json()["session_id"]
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        artifacts = list(db.query(SessionArtifactRecord).filter_by(session_id=session_id).order_by(SessionArtifactRecord.id.asc()))
        proposals = list(db.query(ResourceProposalRecord).filter_by(session_id=session_id).order_by(ResourceProposalRecord.id.asc()))
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=5, before_message_id=None)

    assert artifacts == []
    assert len(proposals) == 1
    assert proposals[0].current_state == "pending_approval"
    assert "Approval required for `send_message`" in messages[-1].content


def test_governed_capability_requires_approval_then_activates_on_later_turn(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'governance.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "send hello channel",
            "peer_id": "peer",
        },
    )
    assert first.status_code == 202
    session_id = first.json()["session_id"]
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        proposal = db.query(ResourceProposalRecord).filter_by(session_id=session_id).one()
        events = list(
            db.query(GovernanceTranscriptEventRecord)
            .filter_by(session_id=session_id)
            .order_by(GovernanceTranscriptEventRecord.created_at.asc())
        )
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=5, before_message_id=None)

    assert proposal.current_state == "pending_approval"
    assert [event.event_kind for event in events] == ["proposal_created", "approval_requested"]
    assert "Approval required for `send_message`" in messages[-1].content

    pending = client.get(f"/sessions/{session_id}/governance/pending")
    assert pending.status_code == 200
    pending_body = pending.json()
    assert pending_body == [
            {
                "proposal_id": proposal.id,
                "message_id": proposal.message_id,
                "agent_id": "default-agent",
                "requested_by": "sender",
            "current_state": "pending_approval",
            "resource_kind": "tool",
            "resource_version_id": proposal.latest_version_id,
            "capability_name": "send_message",
            "typed_action_id": "tool.send_message",
            "content_hash": pending_body[0]["content_hash"],
            "canonical_params": {"text": "hello channel"},
            "canonical_params_json": '{"text":"hello channel"}',
            "scope_kind": "session_agent",
            "next_action": f"approve {proposal.id}",
            "proposed_at": pending_body[0]["proposed_at"],
            "pending_approval_at": pending_body[0]["pending_approval_at"],
        }
    ]

    approve = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": f"approve {proposal.id}",
            "peer_id": "peer",
        },
    )
    assert approve.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    pending_after_approval = client.get(f"/sessions/{session_id}/governance/pending")
    assert pending_after_approval.status_code == 200
    assert pending_after_approval.json() == []

    retry = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-3",
            "sender_id": "sender",
            "content": "send hello channel",
            "peer_id": "peer",
        },
    )
    assert retry.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        approvals = list(db.query(ResourceApprovalRecord).filter_by(proposal_id=proposal.id))
        active = list(db.query(ActiveResourceRecord).filter_by(proposal_id=proposal.id))
        artifacts = list(db.query(SessionArtifactRecord).filter_by(session_id=session_id).order_by(SessionArtifactRecord.id.asc()))
        deliveries = list(db.query(OutboundDeliveryRecord).filter_by(session_id=session_id).order_by(OutboundDeliveryRecord.id.asc()))
        audits = list(db.query(ToolAuditEventRecord).filter_by(session_id=session_id).order_by(ToolAuditEventRecord.id.asc()))
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=20, before_message_id=None)

    assert len(approvals) == 1
    assert len(active) == 1
    assert active[0].activation_state == "active"
    assert "Approved proposal" in messages[-3].content
    assert messages[-1].content == "Prepared outbound message: hello channel"
    assert [artifact.artifact_kind for artifact in artifacts[-2:]] == ["outbound_intent", "tool_result"]
    assert len(deliveries) == 1
    assert deliveries[0].delivery_kind == "text_chunk"
    assert deliveries[0].status == "sent"
    assert any(audit.event_kind == "approval_decision" for audit in audits)


def test_duplicate_approval_and_later_revocation_are_idempotent(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'revoke.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "send hello again",
            "peer_id": "peer",
        },
    )
    session_id = first.json()["session_id"]
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        proposal = db.query(ResourceProposalRecord).filter_by(session_id=session_id).one()

    approve_one = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": f"approve {proposal.id}",
            "peer_id": "peer",
        },
    )
    approve_two = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-3",
            "sender_id": "sender",
            "content": f"approve {proposal.id}",
            "peer_id": "peer",
        },
    )
    assert approve_one.status_code == 202
    assert approve_two.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    revoke = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-4",
            "sender_id": "sender",
            "content": f"revoke {proposal.id}",
            "peer_id": "peer",
        },
    )
    assert revoke.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    blocked_after_revoke = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-5",
            "sender_id": "sender",
            "content": "send hello again",
            "peer_id": "peer",
        },
    )
    assert blocked_after_revoke.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        approvals = list(db.query(ResourceApprovalRecord).filter_by(proposal_id=proposal.id))
        active = list(db.query(ActiveResourceRecord).filter_by(proposal_id=proposal.id))
        refreshed_proposal = db.get(ResourceProposalRecord, proposal.id)
        events = list(
            db.query(GovernanceTranscriptEventRecord)
            .filter_by(session_id=session_id)
            .order_by(GovernanceTranscriptEventRecord.created_at.asc())
        )

    assert len(approvals) == 1
    assert approvals[0].revoked_at is not None
    assert len(active) == 1
    assert active[0].activation_state == "revoked"
    assert refreshed_proposal.current_state == "approved"
    assert events[-1].event_kind == "approval_requested"


def test_long_session_overflow_persists_degraded_manifest_and_repair_job(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'overflow.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based", runtime_transcript_context_limit=1)
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "web",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    second = client.post(
        "/inbound/message",
        json={
            "channel_kind": "web",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "follow up",
            "peer_id": "peer",
        },
    )
    assert first.status_code == 202
    assert second.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    session_id = second.json()["session_id"]
    with manager.session() as db:
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=10, before_message_id=None)
        manifest = (
            db.query(ContextManifestRecord)
            .filter_by(session_id=session_id)
            .order_by(ContextManifestRecord.id.desc())
            .first()
        )
        jobs = list(
            db.query(OutboxJobRecord)
            .filter_by(session_id=session_id)
            .order_by(OutboxJobRecord.id.asc())
        )

    assert messages[-1].content == (
        "I could not safely fit the required session context into the model window for this turn. "
        "Continuity repair has been queued."
    )
    assert manifest is not None
    assert manifest.degraded is True
    assert json.loads(manifest.manifest_json)["assembly_mode"] == "degraded_failure"
    assert any(job.job_kind == "continuity_repair" for job in jobs)


def test_governance_replay_survives_normalized_state_loss(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'governance-replay.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "send hello channel",
            "peer_id": "peer",
        },
    )
    session_id = first.json()["session_id"]
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        proposal = db.query(ResourceProposalRecord).filter_by(session_id=session_id).one()

    client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": f"approve {proposal.id}",
            "peer_id": "peer",
        },
    )
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        db.query(ResourceApprovalRecord).delete()
        db.query(ActiveResourceRecord).delete()
        db.commit()

    retry = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-3",
            "sender_id": "sender",
            "content": "send hello channel",
            "peer_id": "peer",
        },
    )
    assert retry.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=20, before_message_id=None)

    assert messages[-1].content == "Prepared outbound message: hello channel"


def test_inbound_attachments_are_normalized_before_context_manifest(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'attachments.db'}"
    media_root = tmp_path / "media-store"
    source_file = tmp_path / "note.txt"
    source_file.write_text("attachment body")
    settings = Settings(database_url=database_url, runtime_mode="rule_based", media_storage_root=str(media_root))
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    response = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello with attachment",
            "peer_id": "peer",
            "attachments": [
                {
                    "source_url": source_file.resolve().as_uri(),
                    "mime_type": "text/plain",
                    "filename": "note.txt",
                    "provider_metadata": {"provider": "test"},
                }
            ],
        },
    )
    assert response.status_code == 202
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        attachments = list(
            db.query(MessageAttachmentRecord)
            .filter_by(message_id=response.json()["message_id"])
            .order_by(MessageAttachmentRecord.id.asc())
        )
        manifest = (
            db.query(ContextManifestRecord)
            .filter_by(session_id=response.json()["session_id"])
            .order_by(ContextManifestRecord.id.desc())
            .first()
        )

    assert len(attachments) == 1
    assert attachments[0].normalization_status == "stored"
    assert attachments[0].storage_key is not None
    assert media_root.joinpath(attachments[0].storage_key).exists()
    assert manifest is not None
    manifest_payload = json.loads(manifest.manifest_json)
    assert manifest_payload["attachment_ids"] == [attachments[0].id]
    assert manifest_payload["attachments"][0]["storage_key"] == attachments[0].storage_key


def test_scheduler_replay_reuses_fire_run_and_transcript_trigger(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'scheduler-replay.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    inbound = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )
    assert inbound.status_code == 202
    session_id = inbound.json()["session_id"]
    drain_queue(manager, app.state.run_execution_service)

    with manager.session() as db:
        job = ScheduledJobRecord(
            job_key="job-1",
            agent_id="agent-1",
            target_kind="session",
            session_id=session_id,
            cron_expr="0 * * * *",
            payload_json=json.dumps({"prompt": "scheduled ping"}, sort_keys=True),
            enabled=1,
        )
        db.add(job)
        db.commit()

    scheduler_service = SchedulerService(
        jobs_repository=JobsRepository(),
        session_repository=SessionRepository(),
        submit_scheduler_run=app.state.session_service.submit_scheduler_fire,
    )
    scheduled_for = datetime(2026, 3, 23, 15, 0, tzinfo=timezone.utc)

    with manager.session() as db:
        first_run_id = scheduler_service.submit_due_job(db, job_key="job-1", scheduled_for=scheduled_for)
        db.commit()

    with manager.session() as db:
        second_run_id = scheduler_service.submit_due_job(db, job_key="job-1", scheduled_for=scheduled_for)
        db.commit()

    assert second_run_id == first_run_id

    with manager.session() as db:
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=20, before_message_id=None)
        scheduler_messages = [message for message in messages if message.sender_id == "scheduler:job-1"]
        refreshed_job = SessionRepository().get_scheduled_job_by_key(db, job_key="job-1")
        fire = db.query(ScheduledJobFireRecord).filter_by(fire_key=f"job-1:{scheduled_for.isoformat()}").one()

    assert len(scheduler_messages) == 1
    assert scheduler_messages[0].role == "user"
    assert scheduler_messages[0].external_message_id is None
    assert refreshed_job is not None
    assert refreshed_job.last_fired_at.replace(tzinfo=timezone.utc) == scheduled_for
    assert fire is not None
    assert fire.status == "submitted"


def test_expired_lane_lease_recovers_abandoned_run_before_later_same_session_run(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale-lane-recovery.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender",
            "content": "first",
            "peer_id": "peer",
        },
    )
    second = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender",
            "content": "second",
            "peer_id": "peer",
        },
    )
    assert first.status_code == 202
    assert second.status_code == 202

    repository = JobsRepository()
    now = datetime.now(timezone.utc)
    later = now + timedelta(seconds=10)

    with manager.session() as db:
        claim = repository.claim_next_eligible_run(
            db,
            worker_id="crashed-worker",
            lease_seconds=1,
            global_concurrency_limit=1,
            now=now,
        )
        assert claim is not None
        repository.mark_running(db, run_id=claim.run.id, worker_id="crashed-worker", started_at=now)
        db.commit()

    with manager.session() as db:
        recovered = repository.claim_next_eligible_run(
            db,
            worker_id="replacement-worker",
            lease_seconds=60,
            global_concurrency_limit=1,
            now=later,
        )
        assert recovered is not None
        first_run = db.get(ExecutionRunRecord, first.json()["run_id"])
        second_run = db.get(ExecutionRunRecord, second.json()["run_id"])
        assert first_run is not None
        assert second_run is not None
        assert recovered.run.id == first_run.id
        assert first_run.status == ExecutionRunStatus.CLAIMED.value
        assert first_run.attempt_count == 1
        assert second_run.status == ExecutionRunStatus.QUEUED.value


def test_global_concurrency_limit_blocks_second_claim_until_slot_is_released(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'global-cap.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    first = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-1",
            "sender_id": "sender-1",
            "content": "first",
            "peer_id": "peer-1",
        },
    )
    second = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "msg-2",
            "sender_id": "sender-2",
            "content": "second",
            "peer_id": "peer-2",
        },
    )
    assert first.status_code == 202
    assert second.status_code == 202

    repository = JobsRepository()
    now = datetime.now(timezone.utc)

    with manager.session() as db:
        claim = repository.claim_next_eligible_run(
            db,
            worker_id="worker-1",
            lease_seconds=60,
            global_concurrency_limit=1,
            now=now,
        )
        assert claim is not None
        blocked = repository.claim_next_eligible_run(
            db,
            worker_id="worker-2",
            lease_seconds=60,
            global_concurrency_limit=1,
            now=now,
        )
        assert blocked is None
        active_slots = list(db.query(GlobalRunLeaseRecord).order_by(GlobalRunLeaseRecord.slot_key.asc()))
        assert len(active_slots) == 1
        assert active_slots[0].execution_run_id == claim.run.id
        repository.release_session_lease(
            db,
            lane_key=claim.run.lane_key,
            execution_run_id=claim.run.id,
            worker_id="worker-1",
        )
        repository.release_global_slot(
            db,
            execution_run_id=claim.run.id,
            worker_id="worker-1",
        )
        run = db.get(ExecutionRunRecord, claim.run.id)
        assert run is not None
        run.status = ExecutionRunStatus.CANCELLED.value
        db.commit()

    with manager.session() as db:
        next_claim = repository.claim_next_eligible_run(
            db,
            worker_id="worker-2",
            lease_seconds=60,
            global_concurrency_limit=1,
            now=now,
        )
        assert next_claim is not None
        assert next_claim.run.id == second.json()["run_id"]


def test_scheduler_routing_tuple_target_creates_session_via_routing_rules(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'scheduler-routing-tuple.db'}"
    settings = Settings(database_url=database_url, runtime_mode="rule_based")
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)

    app = create_app(settings=settings, session_manager=manager)

    with manager.session() as db:
        job = ScheduledJobRecord(
            job_key="job-routing",
            agent_id="agent-1",
            target_kind="routing_tuple",
            channel_kind="slack",
            channel_account_id="acct",
            peer_id="peer-routing",
            cron_expr="0 * * * *",
            payload_json=json.dumps({"prompt": "scheduled ping"}, sort_keys=True),
            enabled=1,
        )
        db.add(job)
        db.commit()

    scheduler_service = SchedulerService(
        jobs_repository=JobsRepository(),
        session_repository=SessionRepository(),
        submit_scheduler_run=app.state.session_service.submit_scheduler_fire,
    )
    scheduled_for = datetime(2026, 3, 23, 18, 0, tzinfo=timezone.utc)

    with manager.session() as db:
        run_id = scheduler_service.submit_due_job(db, job_key="job-routing", scheduled_for=scheduled_for)
        db.commit()
        run = db.get(ExecutionRunRecord, run_id)
        assert run is not None
        session = SessionRepository().get_session(db, run.session_id)
        assert session is not None
        assert session.session_key == "slack:acct:direct:peer-routing:main"
        message = SessionRepository().get_message(db, message_id=run.message_id)
        assert message is not None
        assert message.sender_id == "scheduler:job-routing"
        assert message.role == "user"
        assert message.external_message_id is None
