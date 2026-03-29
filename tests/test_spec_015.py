from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.config.settings import HistoricalAgentProfileOverrideConfig, PolicyProfileConfig, Settings, ToolProfileConfig
from src.db.models import MessageRole
from src.jobs.repository import JobsRepository
from src.policies.service import PolicyService
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


def _delegation_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        runtime_mode="rule_based",
        diagnostics_admin_bearer_token="admin-secret",
        policy_profiles=[
            PolicyProfileConfig(
                key="default",
                remote_execution_enabled=False,
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids=["child-agent"],
            )
        ],
        tool_profiles=[
            ToolProfileConfig(
                key="default",
                allowed_capability_names=["echo_text", "delegate_to_agent"],
            )
        ],
        historical_agent_profile_overrides=[
            HistoricalAgentProfileOverrideConfig(
                agent_id="child-agent",
                model_profile_key="default",
                policy_profile_key="default",
                tool_profile_key="default",
            )
        ],
    )


def test_delegation_service_creates_child_session_and_parent_continuation(session_manager) -> None:
    settings = _delegation_settings(str(session_manager.engine.url))
    app = create_app(settings=settings, session_manager=session_manager)
    repository = SessionRepository()
    jobs = JobsRepository()
    delegation_service = app.state.delegation_service

    with session_manager.session() as db:
        session = repository.get_or_create_session(
            db,
            normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="parent-user",
                    peer_id="peer-1",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db,
            session,
            role=MessageRole.USER.value,
            content="Please research this",
            external_message_id="spec015-parent",
            sender_id="parent-user",
            last_activity_at=datetime.now(timezone.utc),
        )
        run = jobs.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref=f"parent-{message.id}",
            lane_key=session.id,
            max_attempts=2,
        )
        result = delegation_service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"child-agent"},
            ),
            parent_session_id=session.id,
            parent_message_id=message.id,
            parent_run_id=run.id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id="tool-call-1",
            child_agent_id="child-agent",
            task_text="Investigate the docs and summarize findings.",
            delegation_kind="research",
        )
        child_session = repository.get_session(db, result.child_session_id)
        child_message = repository.get_message(db, message_id=delegation_service.repository.get_delegation(db, delegation_id=result.delegation_id).child_message_id)
        assert child_session is not None
        assert child_session.session_kind == "child"
        assert child_session.parent_session_id == session.id
        assert child_session.owner_agent_id == "child-agent"
        assert child_message is not None
        assert child_message.role == MessageRole.SYSTEM.value

        delegation_service.mark_child_run_running(db, child_run_id=result.child_run_id)
        repository.append_message(
            db,
            child_session,
            role=MessageRole.ASSISTANT.value,
            content="Here is the delegated summary.",
            external_message_id=None,
            sender_id="child-agent",
            last_activity_at=datetime.now(timezone.utc),
        )
        payload = delegation_service.handle_child_run_completed(db, child_run_id=result.child_run_id)
        db.commit()

    assert payload is not None
    assert payload.summary_text == "Here is the delegated summary."
    with session_manager.session() as db:
        delegation = delegation_service.repository.get_delegation(db, delegation_id=result.delegation_id)
        parent_message = repository.get_message(db, message_id=delegation.parent_result_message_id)
        parent_run = jobs.get_execution_run(db, delegation.parent_result_run_id)

    assert delegation is not None
    assert delegation.status == "completed"
    assert parent_message is not None
    assert parent_message.role == "system"
    assert parent_run is not None
    assert parent_run.trigger_kind == "delegation_result"


def test_admin_exposes_delegation_routes(session_manager) -> None:
    settings = _delegation_settings(str(session_manager.engine.url))
    client = TestClient(create_app(settings=settings, session_manager=session_manager))
    headers = {"Authorization": "Bearer admin-secret"}

    with session_manager.session() as db:
        repository = SessionRepository()
        jobs = JobsRepository()
        delegation_service = client.app.state.delegation_service
        session = repository.get_or_create_session(
            db,
            normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="parent-user",
                    peer_id="peer-2",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db,
            session,
            role="user",
            content="delegate",
            external_message_id="spec015-parent-admin",
            sender_id="parent-user",
            last_activity_at=datetime.now(timezone.utc),
        )
        run = jobs.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref=f"admin-{message.id}",
            lane_key=session.id,
            max_attempts=2,
        )
        created = delegation_service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"child-agent"},
            ),
            parent_session_id=session.id,
            parent_message_id=message.id,
            parent_run_id=run.id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id="tool-call-admin",
            child_agent_id="child-agent",
            task_text="admin listing",
            delegation_kind="general",
        )
        db.commit()

    session_response = client.get(f"/sessions/{session.id}/delegations", headers=headers)
    detail_response = client.get(f"/delegations/{created.delegation_id}", headers=headers)
    events_response = client.get(f"/delegations/{created.delegation_id}/events", headers=headers)
    agent_response = client.get("/agents/child-agent/delegations", headers=headers)

    assert session_response.status_code == 200
    assert detail_response.status_code == 200
    assert events_response.status_code == 200
    assert agent_response.status_code == 200
    assert session_response.json()[0]["id"] == created.delegation_id
    assert detail_response.json()["child_agent_id"] == "child-agent"
    assert events_response.json()[0]["event_kind"] == "queued"
    assert agent_response.json()[0]["id"] == created.delegation_id
