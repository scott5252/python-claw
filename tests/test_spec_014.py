from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from src.agents.bootstrap import bootstrap_agent_profiles
from src.config.settings import Settings
from src.db.models import AgentProfileRecord, ModelProfileRecord
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository


@dataclass
class CapturingGraph:
    seen_bindings: list[tuple[str, str, str]]

    def invoke(self, **kwargs):
        binding = kwargs["execution_binding"]
        self.seen_bindings.append(
            (binding.agent_id, binding.model_profile_key, binding.policy_profile_key)
        )

        class State:
            response_text = "captured"
            assistant_message_id = None
            degraded = False

        return State()

    def persist_final_state(self, *, db, state):
        return state


def test_inbound_bootstraps_owner_and_persists_profile_keys(session_manager) -> None:
    settings = Settings(database_url=str(session_manager.engine.url), runtime_mode="rule_based")
    app = create_app(settings=settings, session_manager=session_manager)
    client = TestClient(app)

    response = client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "spec014-msg-1",
            "sender_id": "sender",
            "content": "hello",
            "peer_id": "peer",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    with session_manager.session() as db:
        session = SessionRepository().get_session(db, payload["session_id"])
        run = JobsRepository().get_execution_run(db, payload["run_id"])

    assert session is not None
    assert session.owner_agent_id == settings.default_agent_id
    assert session.session_kind == "primary"
    assert run is not None
    assert run.agent_id == settings.default_agent_id
    assert run.model_profile_key == "default"
    assert run.policy_profile_key == "default"
    assert run.tool_profile_key == "default"


def test_existing_session_keeps_owner_after_default_agent_changes(session_manager) -> None:
    initial_settings = Settings(database_url=str(session_manager.engine.url), runtime_mode="rule_based")
    initial_app = create_app(settings=initial_settings, session_manager=session_manager)
    initial_client = TestClient(initial_app)
    first = initial_client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "spec014-msg-2",
            "sender_id": "sender",
            "content": "first",
            "peer_id": "peer",
        },
    )
    assert first.status_code == 202
    session_id = first.json()["session_id"]

    changed_settings = Settings(
        database_url=str(session_manager.engine.url),
        runtime_mode="rule_based",
        default_agent_id="agent-2",
    )
    with session_manager.session() as db:
        bootstrap_agent_profiles(db, settings=changed_settings)
        db.commit()
    changed_app = create_app(settings=changed_settings, session_manager=session_manager)
    changed_client = TestClient(changed_app)
    second = changed_client.post(
        "/inbound/message",
        json={
            "channel_kind": "slack",
            "channel_account_id": "acct",
            "external_message_id": "spec014-msg-3",
            "sender_id": "sender",
            "content": "second",
            "peer_id": "peer",
        },
    )

    assert second.status_code == 202
    with session_manager.session() as db:
        session = SessionRepository().get_session(db, session_id)
        run = JobsRepository().get_execution_run(db, second.json()["run_id"])

    assert session is not None
    assert session.owner_agent_id == initial_settings.default_agent_id
    assert run is not None
    assert run.agent_id == initial_settings.default_agent_id


def test_worker_uses_persisted_profile_keys_when_agent_profile_links_change(session_manager, settings: Settings) -> None:
    repository = SessionRepository()
    jobs = JobsRepository()
    with session_manager.session() as db:
        session = repository.get_or_create_session(
            db,
            routing=normalize_routing_input(
                RoutingInput(
                    channel_kind="webchat",
                    channel_account_id="acct",
                    sender_id="sender",
                    peer_id="peer",
                )
            ),
            owner_agent_id="default-agent",
        )
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="spec014-msg-4",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        run = jobs.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=message.id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref="spec014-run-1",
            lane_key=session.id,
            max_attempts=1,
        )

        alt = ModelProfileRecord(
            profile_key="alt",
            runtime_mode="rule_based",
            provider=None,
            model_name=None,
            temperature=None,
            max_output_tokens=None,
            timeout_seconds=30,
            tool_call_mode="auto",
            streaming_enabled=1,
            enabled=1,
        )
        db.add(alt)
        db.flush()
        agent = db.get(AgentProfileRecord, "default-agent")
        assert agent is not None
        agent.default_model_profile_id = alt.id
        db.commit()

    seen: list[tuple[str, str, str]] = []
    service = RunExecutionService(
        settings=settings,
        jobs_repository=JobsRepository(),
        session_repository=repository,
        concurrency_service=SessionConcurrencyService(repository=JobsRepository(), lease_seconds=60, global_concurrency_limit=4),
        assistant_graph_factory=lambda binding: CapturingGraph(seen),
        failure_classifier=FailureClassifier(),
        base_backoff_seconds=1,
        max_backoff_seconds=10,
    )

    with session_manager.session() as db:
        processed = service.process_next_run(db, worker_id="worker-014")
        db.commit()

    assert processed == run.id
    assert seen == [("default-agent", "default", "default")]


def test_agent_profile_admin_endpoints_require_operator_access(client, session_manager) -> None:
    assert client.get("/agents").status_code == 401
    headers = {"Authorization": "Bearer admin-secret"}

    agents = client.get("/agents", headers=headers)
    models = client.get("/model-profiles", headers=headers)

    assert agents.status_code == 200
    assert any(item["agent_id"] == "default-agent" for item in agents.json())
    assert models.status_code == 200
    assert any(item["profile_key"] == "default" for item in models.json())
