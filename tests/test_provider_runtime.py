from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.config.settings import Settings
from src.graphs.prompts import PROMPT_STRATEGY_ID, build_prompt_payload
from src.graphs.state import AssistantState, ConversationMessage
from src.providers.models import ProviderBackedModelAdapter, ProviderClient, ProviderError
from src.tools.local_safe import create_echo_text_tool
from src.tools.messaging import create_send_message_tool
from src.tools.registry import ToolRegistry


def _build_state() -> AssistantState:
    state = AssistantState(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="user-1",
        user_text="hello there",
        messages=[ConversationMessage(role="assistant", content="[summary] prior context", sender_id="agent-1")],
        context_manifest={
            "attachments": [
                {
                    "id": 10,
                    "media_kind": "document",
                    "mime_type": "text/plain",
                    "storage_key": "attachments/doc.txt",
                    "filename": "doc.txt",
                }
            ]
        },
    )
    registry = ToolRegistry(factories={"echo_text": create_echo_text_tool, "send_message": create_send_message_tool})
    visible_tools = list(
        registry.bind_tools(
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
            policy_service=type(
                "Policy",
                (),
                {
                    "is_tool_visible": staticmethod(lambda **_: True),
                },
            )(),
        ).values()
    )
    state.llm_prompt = build_prompt_payload(state=state, visible_tools=visible_tools, tool_call_mode="auto")
    return state


@dataclass
class FakeProviderClient(ProviderClient):
    response: dict[str, object] | None = None
    error: Exception | None = None
    calls: int = 0

    def create_response(self, *, prompt: dict[str, object], tools: list[dict[str, object]], settings: Settings) -> dict[str, object]:
        self.calls += 1
        assert isinstance(prompt["input"], str)
        assert settings.llm_model == "gpt-4o-mini"
        if self.error is not None:
            raise self.error
        assert tools
        return self.response or {"output_text": "", "output": []}


def test_prompt_payload_contains_required_sections() -> None:
    state = _build_state()
    prompt = state.llm_prompt

    assert prompt is not None
    assert prompt.system_instructions
    assert prompt.conversation[-1]["content"] == "hello there"
    assert prompt.attachments[0]["storage_key"] == "attachments/doc.txt"
    assert [tool.name for tool in prompt.tools] == ["echo_text", "send_message"]
    assert "approval" in prompt.approval_guidance.lower()
    assert "tool requests" in prompt.response_contract
    assert prompt.metadata["prompt_strategy_id"] == PROMPT_STRATEGY_ID


def test_provider_adapter_translates_plain_text_response() -> None:
    settings = Settings(database_url="sqlite://", runtime_mode="provider", llm_api_key="test-key")
    client = FakeProviderClient(response={"output_text": "Natural language reply", "output": []})
    adapter = ProviderBackedModelAdapter(settings=settings, client=client)

    result = adapter.complete_turn(state=_build_state(), available_tools=["echo_text"])

    assert result.needs_tools is False
    assert result.response_text == "Natural language reply"
    assert result.execution_metadata["provider_name"] == "openai"
    assert result.execution_metadata["provider_attempt_count"] == 1


def test_provider_adapter_translates_tool_calls_and_generates_correlation_ids() -> None:
    settings = Settings(database_url="sqlite://", runtime_mode="provider", llm_api_key="test-key")
    client = FakeProviderClient(
        response={
            "output": [
                {
                    "type": "function_call",
                    "name": "echo_text",
                    "arguments": {"text": "hello"},
                }
            ]
        }
    )
    adapter = ProviderBackedModelAdapter(settings=settings, client=client)

    result = adapter.complete_turn(state=_build_state(), available_tools=["echo_text"])

    assert result.needs_tools is True
    assert len(result.tool_requests) == 1
    assert result.tool_requests[0].capability_name == "echo_text"
    assert result.tool_requests[0].arguments == {"text": "hello"}
    assert result.tool_requests[0].correlation_id


def test_provider_adapter_rejects_malformed_tool_calls_safely() -> None:
    settings = Settings(database_url="sqlite://", runtime_mode="provider", llm_api_key="test-key")
    client = FakeProviderClient(
        response={
            "output": [
                {
                    "type": "function_call",
                    "name": "send_message",
                    "call_id": "call-1",
                    "arguments": "not-json",
                }
            ]
        }
    )
    adapter = ProviderBackedModelAdapter(settings=settings, client=client)

    result = adapter.complete_turn(state=_build_state(), available_tools=["send_message"])

    assert result.needs_tools is False
    assert result.tool_requests == []
    assert result.rejected_tool_requests[0].capability_name == "send_message"
    assert result.execution_metadata["semantic_fallback_kind"] == "rejected_tool_request"
    assert "could not safely use" in result.response_text


def test_provider_adapter_retries_retryable_provider_errors() -> None:
    settings = Settings(database_url="sqlite://", runtime_mode="provider", llm_api_key="test-key", llm_max_retries=1)
    client = FakeProviderClient(error=ProviderError(category="provider_timeout", retryable=True, detail="timeout"))
    adapter = ProviderBackedModelAdapter(settings=settings, client=client)

    with pytest.raises(ProviderError):
        adapter.complete_turn(state=_build_state(), available_tools=["echo_text"])

    assert client.calls == 2


def test_provider_settings_validation_requires_api_key_for_provider_mode() -> None:
    with pytest.raises(ValueError):
        Settings(database_url="sqlite://", runtime_mode="provider", llm_api_key=None)

