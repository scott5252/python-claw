from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.capabilities.activation import ActivationController
from src.config.settings import Settings
from src.db.base import Base
from src.db.models import (
    ActiveResourceRecord,
    DedupeStatus,
    GovernanceTranscriptEventRecord,
    InboundDedupeRecord,
    ResourceApprovalRecord,
    ResourceProposalRecord,
    SessionArtifactRecord,
    ToolAuditEventRecord,
)
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.graphs.state import AssistantState, ModelTurnResult, ToolRequest
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService
from src.providers.models import ModelAdapter
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
            transcript_context_limit=10,
        )
    ).build()
    return SessionService(
        repository=repository,
        assistant_graph=graph,
        idempotency_service=IdempotencyService(),
        default_agent_id="agent-1",
        dedupe_retention_days=30,
        dedupe_stale_after_seconds=1,
        page_default_limit=2,
        page_max_limit=5,
    )


def test_restart_safe_session_reuse_and_duplicate_replay(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    settings = Settings(
        database_url=database_url,
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
    settings = Settings(database_url=database_url, dedupe_stale_after_seconds=1)
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
    assert recovered.status_code == 201
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

    page_one = client.get(f"/sessions/{session_id}/messages", params={"limit": 2})
    body_one = page_one.json()
    assert [item["content"] for item in body_one["items"]] == ["three", "Received: three"]
    assert body_one["next_before_message_id"] == 5

    page_two = client.get(
        f"/sessions/{session_id}/messages",
        params={"limit": 2, "before_message_id": 5},
    )
    body_two = page_two.json()
    assert [item["content"] for item in body_two["items"]] == ["two", "Received: two"]


def test_unapproved_tool_request_fails_closed_and_records_failure(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'unapproved.db'}"
    settings = Settings(database_url=database_url)
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
    assert response.status_code == 201
    session_id = response.json()["session_id"]

    with manager.session() as db:
        artifacts = list(db.query(SessionArtifactRecord).filter_by(session_id=session_id).order_by(SessionArtifactRecord.id.asc()))
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=5, before_message_id=None)

    assert [artifact.artifact_kind for artifact in artifacts] == ["tool_proposal", "tool_result"]
    assert json.loads(artifacts[-1].payload_json)["error"] == "tool not available in runtime context"
    assert messages[-1].content == "I could not complete that tool request."


def test_governed_capability_requires_approval_then_activates_on_later_turn(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'governance.db'}"
    settings = Settings(database_url=database_url)
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
    assert first.status_code == 201
    session_id = first.json()["session_id"]

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
    assert approve.status_code == 201

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
    assert retry.status_code == 201

    with manager.session() as db:
        approvals = list(db.query(ResourceApprovalRecord).filter_by(proposal_id=proposal.id))
        active = list(db.query(ActiveResourceRecord).filter_by(proposal_id=proposal.id))
        artifacts = list(db.query(SessionArtifactRecord).filter_by(session_id=session_id).order_by(SessionArtifactRecord.id.asc()))
        audits = list(db.query(ToolAuditEventRecord).filter_by(session_id=session_id).order_by(ToolAuditEventRecord.id.asc()))
        messages = SessionRepository().list_messages(db, session_id=session_id, limit=20, before_message_id=None)

    assert len(approvals) == 1
    assert len(active) == 1
    assert active[0].activation_state == "active"
    assert "Approved proposal" in messages[-3].content
    assert messages[-1].content == "Prepared outbound message: hello channel"
    assert [artifact.artifact_kind for artifact in artifacts[-2:]] == ["outbound_intent", "tool_result"]
    assert any(audit.event_kind == "approval_decision" for audit in audits)


def test_duplicate_approval_and_later_revocation_are_idempotent(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'revoke.db'}"
    settings = Settings(database_url=database_url)
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
    assert approve_one.status_code == 201
    assert approve_two.status_code == 201

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
    assert revoke.status_code == 201

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
    assert blocked_after_revoke.status_code == 201

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
