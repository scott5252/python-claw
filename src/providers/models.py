from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.graphs.state import AssistantState, ModelTurnResult, ToolRequest, ToolRuntimeServices


class ModelAdapter:
    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        raise NotImplementedError

    def runtime_services(self) -> ToolRuntimeServices:
        return ToolRuntimeServices()


@dataclass
class RuleBasedModelAdapter(ModelAdapter):
    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        text = state.user_text.strip()
        lowered = text.lower()

        if lowered.startswith("echo ") and "echo_text" in available_tools:
            return ModelTurnResult(
                needs_tools=True,
                tool_requests=[
                    ToolRequest(
                        correlation_id=str(uuid4()),
                        capability_name="echo_text",
                        arguments={"text": text[5:]},
                    )
                ],
                response_text="",
            )

        if lowered.startswith("send ") and "send_message" in available_tools:
            return ModelTurnResult(
                needs_tools=True,
                tool_requests=[
                    ToolRequest(
                        correlation_id=str(uuid4()),
                        capability_name="send_message",
                        arguments={"text": text[5:]},
                    )
                ],
                response_text="",
            )

        return ModelTurnResult(
            needs_tools=False,
            tool_requests=[],
            response_text=f"Received: {text}",
        )
