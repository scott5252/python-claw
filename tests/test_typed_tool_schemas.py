from __future__ import annotations

from dataclasses import dataclass

from src.agents.service import ResolvedModelProfile
from src.capabilities.activation import ActivationController
from src.context.service import ContextService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.graphs.prompts import build_prompt_payload
from src.graphs.state import AssistantState, ConversationMessage, ModelTurnResult, ToolRequest
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService, build_approval_identity_hash
from src.providers.models import ModelAdapter, ProviderBackedModelAdapter, ProviderClient
from src.sessions.repository import SessionRepository
from src.tools.local_safe import EchoTextRequest, create_echo_text_tool
from src.tools.messaging import SendMessageRequest, create_send_message_tool
from src.tools.registry import ToolRegistry, ToolSchemaValidationError
from src.tools.remote_exec import RemoteExecRequest, create_remote_exec_tool
from src.tools.typed_actions import get_typed_action


@dataclass
class StubModel(ModelAdapter):
    result: ModelTurnResult

    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        _ = state
        _ = available_tools
        return self.result


@dataclass
class CapturingProviderClient(ProviderClient):
    captured_tools: list[dict[str, object]] | None = None

    def create_response(self, *, prompt: dict[str, object], tools: list[dict[str, object]], runtime_model, settings) -> dict[str, object]:
        _ = prompt
        _ = runtime_model
        _ = settings
        self.captured_tools = tools
        return {"output": [{"type": "function_call", "name": "send_message", "arguments": {"extra": "x"}}]}


def test_fixed_shape_tool_schemas_reject_unknown_fields() -> None:
    echo_tool = create_echo_text_tool(context=None)  # type: ignore[arg-type]
    send_tool = create_send_message_tool(
        context=type("Ctx", (), {"channel_kind": "web", "sender_id": "sender"})()
    )

    assert echo_tool.validate_arguments({"text": "ok"}).model_dump() == EchoTextRequest(text="ok").model_dump()
    assert send_tool.validate_arguments({"text": "hello"}).model_dump() == SendMessageRequest(text="hello").model_dump()

    try:
        echo_tool.validate_arguments({"text": "ok", "extra": "nope"})
    except ToolSchemaValidationError as exc:
        assert exc.code == "invalid_tool_arguments"
        assert exc.issues[0].field_path == "extra"
    else:
        raise AssertionError("expected echo_text extras to be rejected")

    try:
        send_tool.validate_arguments({"text": "   "})
    except ToolSchemaValidationError as exc:
        assert any(issue.field_path == "text" for issue in exc.issues)
    else:
        raise AssertionError("expected blank send_message text to be rejected")


def test_remote_exec_schema_accepts_only_scalar_json_values() -> None:
    tool = create_remote_exec_tool(
        context=type("Ctx", (), {"runtime_services": type("Services", (), {})()})()
    )

    request = tool.validate_arguments({"text": "hello", "count": 3, "enabled": False, "none": None})
    assert tool.canonicalize_arguments(request) == RemoteExecRequest(text="hello", count=3, enabled=False, none=None).model_dump(
        mode="json",
        round_trip=True,
    )

    for invalid in (
        {"tool_call_id": "abc"},
        {"nested": {"x": 1}},
        {"items": [1, 2, 3]},
    ):
        try:
            tool.validate_arguments(invalid)
        except ToolSchemaValidationError as exc:
            assert exc.code == "invalid_tool_arguments"
        else:
            raise AssertionError(f"expected invalid remote_exec payload to fail: {invalid}")


def test_schema_version_changes_approval_identity_without_typed_action_drift() -> None:
    typed_action = get_typed_action("send_message")

    hash_v1 = build_approval_identity_hash(
        tool_schema_name="send_message.input",
        tool_schema_version="1.0",
        canonical_arguments_json='{"text":"hello"}',
    )
    hash_v2 = build_approval_identity_hash(
        tool_schema_name="send_message.input",
        tool_schema_version="2.0",
        canonical_arguments_json='{"text":"hello"}',
    )

    assert typed_action is not None
    assert typed_action.typed_action_id == "tool.send_message"
    assert hash_v1 != hash_v2


def test_provider_tool_export_uses_bound_tool_schema_and_graph_keeps_validation_authority() -> None:
    state = AssistantState(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="user-1",
        user_text="send hi",
        messages=[ConversationMessage(role="user", content="prior", sender_id="user-1")],
    )
    registry = ToolRegistry(factories={"send_message": create_send_message_tool})
    bound_tools = registry.bind_tools(
        context=type(
            "Ctx",
            (),
            {
                "session_id": "session-1",
                "message_id": 1,
                "agent_id": "agent-1",
                "channel_kind": "web",
                "sender_id": "user-1",
                "policy_context": {"classification": None, "approval_map": {}},
                "runtime_services": None,
            },
        )(),
        policy_service=type("Policy", (), {"is_tool_visible": staticmethod(lambda **_: True)})(),
    )
    state.bound_tools = bound_tools
    state.llm_prompt = build_prompt_payload(state=state, visible_tools=list(bound_tools.values()), tool_call_mode="auto")

    client = CapturingProviderClient()
    adapter = ProviderBackedModelAdapter(
        settings=type(
            "Settings",
            (),
                {
                    "llm_disable_tools": False,
                    "llm_tool_call_mode": "auto",
                    "llm_max_tool_requests_per_turn": 4,
                    "llm_provider": "openai",
                    "llm_model": "gpt-4o-mini",
                    "llm_max_retries": 0,
                },
        )(),
        model_profile=ResolvedModelProfile(
            profile_key="default",
            runtime_mode="provider",
            provider="openai",
            model_name="gpt-4o-mini",
            temperature=0.2,
            max_output_tokens=512,
            timeout_seconds=30,
            tool_call_mode="auto",
            streaming_enabled=True,
            base_url=None,
        ),
        client=client,
    )

    result = adapter.complete_turn(state=state, available_tools=["send_message"])

    assert client.captured_tools == [
        {
            "type": "function",
            "name": "send_message",
            "description": bound_tools["send_message"].description,
            "parameters": bound_tools["send_message"].provider_input_schema,
        }
    ]
    assert result.tool_requests[0].arguments == {"extra": "x"}


def test_schema_invalid_governed_request_creates_no_governance_proposal(session_manager) -> None:
    repository = SessionRepository()
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
                            capability_name="send_message",
                            arguments={"text": "hello", "extra": "nope"},
                        )
                    ],
                    response_text="",
                )
            ),
            tool_registry=ToolRegistry(factories={"send_message": create_send_message_tool}),
            audit_sink=ToolAuditSink(),
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(context_window=10),
        )
    ).build()

    with session_manager.session() as db:
        session = repository.get_or_create_session(
            db,
            routing=type(
                "Routing",
                (),
                {
                    "session_key": "web:acct:peer",
                    "channel_kind": "web",
                    "channel_account_id": "acct",
                    "scope_kind": "direct",
                    "peer_id": "peer",
                    "group_id": None,
                    "scope_name": "main",
                },
            )(),
        )
        message = repository.append_message(
            db,
            session,
            role="user",
            content="please send",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=session.created_at,
        )
        state = graph.invoke(
            db=db,
            session_id=session.id,
            message_id=message.id,
            agent_id="agent-1",
            channel_kind="web",
            sender_id="sender",
            user_text="please send",
        )
        proposals = repository.list_pending_approvals(db, session_id=session.id)

    assert proposals == []
    assert "Invalid arguments for `send_message`" in state.response_text
