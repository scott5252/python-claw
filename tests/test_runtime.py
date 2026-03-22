from __future__ import annotations

import json
from dataclasses import dataclass

from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.graphs.state import AssistantState, ModelTurnResult, ToolRequest, ToolRuntimeContext, ToolRuntimeServices
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService
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


def _create_session(session_manager):
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
        repository.append_message(
            db,
            session,
            role="user",
            content="hello",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=session.created_at,
        )
        db.commit()
        return session.id


def test_graph_branches_deterministically_without_tools(session_manager) -> None:
    session_id = _create_session(session_manager)
    repository = SessionRepository()
    graph = GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=PolicyService(),
            model=StubModel(
                ModelTurnResult(
                    needs_tools=False,
                    tool_requests=[],
                    response_text="plain response",
                )
            ),
            tool_registry=ToolRegistry(factories={}),
            audit_sink=ToolAuditSink(),
            transcript_context_limit=10,
        )
    ).build()

    with session_manager.session() as db:
        state = graph.invoke(
            db=db,
            session_id=session_id,
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
        agent_id="agent-1",
        channel_kind="web",
        sender_id="sender-1",
        policy_context={"scope": "test"},
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
    session_id = _create_session(session_manager)
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

    graph = GraphFactory(
        GraphDependencies(
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
            tool_registry=ToolRegistry(factories={"explode": failing_factory}),
            audit_sink=ToolAuditSink(),
            transcript_context_limit=10,
        )
    ).build()

    with session_manager.session() as db:
        state = graph.invoke(
            db=db,
            session_id=session_id,
            agent_id="agent-1",
            channel_kind="web",
            sender_id="sender",
            user_text="trigger",
        )
        artifacts = repository.list_artifacts(db, session_id=session_id)
        db.commit()

    assert state.response_text == "I could not complete that tool request."
    assert [artifact.artifact_kind for artifact in artifacts] == ["tool_proposal", "tool_result"]
    assert json.loads(artifacts[-1].payload_json)["error"] == "boom"
