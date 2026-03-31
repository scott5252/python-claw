from __future__ import annotations

import json
from dataclasses import dataclass

from src.capabilities.activation import ActivationController
from src.context.service import ContextService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.graphs.state import AssistantState, ModelTurnResult, ToolRequest, ToolRuntimeContext, ToolRuntimeServices
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService, canonicalize_params, hash_payload
from src.providers.models import ModelAdapter
from src.routing.service import RoutingInput, normalize_routing_input
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository
from src.tools.local_safe import create_echo_text_tool
from src.tools.messaging import create_send_message_tool
from src.tools.registry import ToolDefinition, ToolRegistry


@dataclass
class StubModel(ModelAdapter):
    result: ModelTurnResult

    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        _ = state
        _ = available_tools
        return self.result


@dataclass
class CountingModel(ModelAdapter):
    calls: int = 0

    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        _ = state
        _ = available_tools
        self.calls += 1
        return ModelTurnResult(
            needs_tools=False,
            tool_requests=[],
            response_text="model should not run",
        )


def _create_session(session_manager) -> tuple[str, int]:
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
        message = repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=session.created_at,
        )
        db.commit()
        return session.id, message.id


def _build_graph(*, repository: SessionRepository, model: ModelAdapter, policy_service: PolicyService, registry: ToolRegistry):
    return GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=policy_service,
            model=model,
            tool_registry=registry,
            audit_sink=ToolAuditSink(),
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(context_window=10),
        )
    ).build()


def test_graph_branches_deterministically_without_tools(session_manager) -> None:
    session_id, message_id = _create_session(session_manager)
    repository = SessionRepository()
    graph = _build_graph(
        repository=repository,
        policy_service=PolicyService(),
        model=StubModel(
            ModelTurnResult(
                needs_tools=False,
                tool_requests=[],
                response_text="plain response",
            )
        ),
        registry=ToolRegistry(factories={}),
    )

    with session_manager.session() as db:
        state = graph.invoke(
            db=db,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            channel_kind="web",
            sender_id="sender",
            user_text="hello",
        )
        db.commit()

    assert state.needs_tools is False
    assert state.response_text == "plain response"


def test_graph_consumes_terminal_delegation_result_without_reinvoking_model(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )
    terminal_payload = json.dumps(
        {
            "kind": "delegation_result",
            "delegation_id": "delegation-1",
            "child_agent_id": "deploy-agent",
            "status": "completed",
            "summary_text": "Deployment event posted successfully.",
            "pending_approvals": [],
        },
        sort_keys=True,
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = repository.append_message(
            db,
            session,
            role="system",
            content=terminal_payload,
            external_message_id=None,
            sender_id="system:delegation_result:deploy-agent",
            last_activity_at=session.created_at,
        )
        db.commit()

    model = CountingModel()
    graph = _build_graph(
        repository=repository,
        policy_service=PolicyService(),
        model=model,
        registry=ToolRegistry(factories={}),
    )

    with session_manager.session() as db:
        state = graph.invoke(
            db=db,
            session_id=session.id,
            message_id=message.id,
            agent_id="default-agent",
            channel_kind="web",
            sender_id="system:delegation_result:deploy-agent",
            user_text=terminal_payload,
        )
        db.commit()

    assert model.calls == 0
    assert state.response_text == "Deployment event posted successfully."


def test_registry_filters_tools_by_policy_and_context() -> None:
    captured: list[ToolRuntimeContext] = []

    def contextual_factory(context: ToolRuntimeContext) -> ToolDefinition:
        captured.append(context)
        return create_echo_text_tool(context)

    registry = ToolRegistry(
        factories={
            "echo_text": contextual_factory,
            "send_message": create_send_message_tool,
        }
    )
    context = ToolRuntimeContext(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="sender-1",
        policy_context={"classification": PolicyService().classify_turn(user_text="hello"), "approval_map": {}},
        runtime_services=ToolRuntimeServices(),
    )

    bound = registry.bind_tools(
        context=context,
        policy_service=PolicyService(denied_capabilities={"send_message"}),
    )

    assert sorted(bound.keys()) == ["echo_text"]
    assert captured[0].session_id == "session-1"
    assert captured[0].sender_id == "sender-1"


def test_tool_failure_cannot_fabricate_success_response(session_manager) -> None:
    session_id, message_id = _create_session(session_manager)
    repository = SessionRepository()

    def failing_factory(context: ToolRuntimeContext) -> ToolDefinition:
        _ = context

        def invoke(arguments: dict[str, str]):
            _ = arguments
            raise RuntimeError("boom")

        return ToolDefinition(
            capability_name="explode",
            description="fail on demand",
            invoke=invoke,
        )

    graph = _build_graph(
        repository=repository,
        policy_service=PolicyService(),
        model=StubModel(
            ModelTurnResult(
                needs_tools=True,
                tool_requests=[
                    ToolRequest(
                        correlation_id="corr-1",
                        capability_name="explode",
                        arguments={},
                    )
                ],
                response_text="Tool succeeded",
            )
        ),
        registry=ToolRegistry(factories={"explode": failing_factory}),
    )

    with session_manager.session() as db:
        state = graph.invoke(
            db=db,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            channel_kind="web",
            sender_id="sender",
            user_text="trigger",
        )
        artifacts = repository.list_artifacts(db, session_id=session_id)
        db.commit()

    assert state.response_text == "I could not complete that tool request."
    assert [artifact.artifact_kind for artifact in artifacts] == ["tool_proposal", "tool_result"]
    assert json.loads(artifacts[-1].payload_json)["error"] == "tool not available in runtime context"


def test_worker_persists_assistant_message_after_dispatch(session_manager) -> None:
    session_id, message_id = _create_session(session_manager)
    repository = SessionRepository()
    graph = _build_graph(
        repository=repository,
        policy_service=PolicyService(),
        model=StubModel(
            ModelTurnResult(
                needs_tools=False,
                tool_requests=[],
                response_text="plain streamed response",
            )
        ),
        registry=ToolRegistry(factories={}),
    )

    class CheckingDispatcher:
        def dispatch_run(self, *, db, repository, session, execution_run_id, assistant_text):
            messages = repository.list_messages(db, session_id=session.id, limit=10, before_message_id=None)
            assert [message.role for message in messages] == ["user"]
            assert assistant_text == "plain streamed response"

    with session_manager.session() as db:
        jobs = JobsRepository()
        run = jobs.create_or_get_execution_run(
            db,
            session_id=session_id,
            message_id=message_id,
            agent_id="default-agent",
            trigger_kind="inbound_message",
            trigger_ref="run-test-1",
            lane_key=session_id,
            max_attempts=1,
        )
        db.commit()

    service = RunExecutionService(
        settings=None,
        jobs_repository=JobsRepository(),
        session_repository=repository,
        concurrency_service=SessionConcurrencyService(repository=JobsRepository(), lease_seconds=60, global_concurrency_limit=4),
        assistant_graph_factory=lambda: graph,
        failure_classifier=FailureClassifier(),
        base_backoff_seconds=1,
        max_backoff_seconds=10,
        outbound_dispatcher=CheckingDispatcher(),
    )

    with session_manager.session() as db:
        run_id = service.process_next_run(db, worker_id="worker-1")
        db.commit()
        run = JobsRepository().get_execution_run(db, run_id=run_id)
        messages = repository.list_messages(db, session_id=session_id, limit=10, before_message_id=None)

    assert run is not None
    assert run.status == "completed"
    assert [message.content for message in messages][-1] == "plain streamed response"


def test_canonicalization_and_exact_approval_matching() -> None:
    service = PolicyService()
    canonical = canonicalize_params({"b": 1, "a": {"y": 2, "x": 1}})
    assert canonical == '{"a":{"x":1,"y":2},"b":1}'
    assert hash_payload(canonical) == hash_payload('{"a":{"x":1,"y":2},"b":1}')

    context = ToolRuntimeContext(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="sender-1",
        policy_context={
            "classification": service.classify_turn(user_text="send hello"),
            "approval_map": {
                (
                    "send_message",
                    "tool.send_message",
                    hash_payload(canonicalize_params({"text": "hello"})),
                ): {
                    "proposal_id": "proposal-1",
                    "resource_version_id": "version-1",
                    "content_hash": "content-1",
                    "typed_action_id": "tool.send_message",
                    "canonical_params_json": canonicalize_params({"text": "hello"}),
                    "canonical_params_hash": hash_payload(canonicalize_params({"text": "hello"})),
                    "approval_id": "approval-1",
                    "active_resource_id": "active-1",
                }
            },
        },
        runtime_services=ToolRuntimeServices(),
    )

    match = service.assert_execution_allowed(
        context=context,
        capability_name="send_message",
        arguments={"text": "hello"},
    )
    assert match is not None
    assert match.proposal_id == "proposal-1"

    try:
        service.assert_execution_allowed(
            context=context,
            capability_name="send_message",
            arguments={"text": "different"},
        )
    except PermissionError as exc:
        assert "missing exact approval" in str(exc)
    else:
        raise AssertionError("expected missing-approval failure")
