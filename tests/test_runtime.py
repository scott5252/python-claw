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
