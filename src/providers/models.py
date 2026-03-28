from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from uuid import uuid4
from typing import Iterator

import httpx

from src.config.settings import Settings
from src.graphs.state import (
    AssistantState,
    ModelTurnResult,
    RejectedToolRequest,
    ToolRequest,
    ToolRuntimeServices,
)


class ProviderError(RuntimeError):
    def __init__(self, *, category: str, retryable: bool, detail: str) -> None:
        super().__init__(detail)
        self.category = category
        self.retryable = retryable
        self.detail = detail


class ProviderClient:
    def create_response(
        self,
        *,
        prompt: dict[str, object],
        tools: list[dict[str, object]],
        settings: Settings,
    ) -> dict[str, object]:
        raise NotImplementedError


@dataclass
class OpenAIResponsesClient(ProviderClient):
    def create_response(
        self,
        *,
        prompt: dict[str, object],
        tools: list[dict[str, object]],
        settings: Settings,
    ) -> dict[str, object]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError(
                category="provider_unavailable",
                retryable=False,
                detail="openai dependency is not installed",
            ) from exc

        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url or None, timeout=settings.llm_timeout_seconds)
        try:
            response = client.responses.create(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_output_tokens=settings.llm_max_output_tokens,
                input=prompt["input"],
                tools=tools or None,
            )
        except Exception as exc:  # pragma: no cover - exercised through error mapping unit tests
            raise map_provider_exception(exc) from exc

        return response.model_dump()


class ModelAdapter:
    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        raise NotImplementedError

    def runtime_services(self) -> ToolRuntimeServices:
        return ToolRuntimeServices()

    def stream_final_answer(self, *, state: AssistantState, available_tools: list[str]) -> tuple[list[str], ModelTurnResult]:
        result = self.complete_turn(state=state, available_tools=available_tools)
        deltas = [result.response_text] if result.response_text else []
        return deltas, result


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

        return ModelTurnResult(
            needs_tools=False,
            tool_requests=[],
            response_text=f"Received: {text}",
            execution_metadata={
                "provider_name": "rule_based",
                "model_name": "rule-based-adapter",
                "prompt_strategy_id": state.llm_prompt.metadata["prompt_strategy_id"] if state.llm_prompt else "rule-based",
                "tool_call_mode": "auto",
                "provider_attempt_count": 1,
                "semantic_fallback_kind": None,
            },
        )

    def stream_final_answer(self, *, state: AssistantState, available_tools: list[str]) -> tuple[list[str], ModelTurnResult]:
        result = self.complete_turn(state=state, available_tools=available_tools)
        text = result.response_text
        deltas = [text[index : index + 24] for index in range(0, len(text), 24)] if text else []
        return deltas, result


def map_provider_exception(exc: Exception) -> ProviderError:
    detail = str(exc)
    lowered = detail.lower()
    if isinstance(exc, httpx.TimeoutException) or "timeout" in lowered:
        return ProviderError(category="provider_timeout", retryable=True, detail=f"provider request timed out: {detail}")
    if isinstance(exc, httpx.ConnectError) or "unavailable" in lowered or "connection" in lowered:
        return ProviderError(category="provider_unavailable", retryable=True, detail=f"provider unavailable: {detail}")
    if "auth" in lowered or "unauthorized" in lowered or "api key" in lowered:
        return ProviderError(category="provider_auth", retryable=False, detail=f"provider authentication failed: {detail}")
    if "rate limit" in lowered or "429" in lowered:
        return ProviderError(category="provider_rate_limited", retryable=True, detail=f"provider rate limited: {detail}")
    return ProviderError(category="provider_unexpected_internal", retryable=False, detail=f"provider request failed: {detail}")


def _serialize_prompt(state: AssistantState) -> dict[str, object]:
    if state.llm_prompt is None:
        raise ProviderError(
            category="provider_unexpected_internal",
            retryable=False,
            detail="missing prompt payload",
        )

    payload = {
        "system_instructions": state.llm_prompt.system_instructions,
        "conversation": state.llm_prompt.conversation,
        "attachments": state.llm_prompt.attachments,
        "context_sections": state.llm_prompt.context_sections,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "usage_guidance": tool.usage_guidance,
                "input_schema": tool.input_schema,
                "tool_schema_name": tool.tool_schema_name,
                "schema_version": tool.schema_version,
                "requires_approval": tool.requires_approval,
                "governance_hint": tool.governance_hint,
            }
            for tool in state.llm_prompt.tools
        ],
        "approval_guidance": state.llm_prompt.approval_guidance,
        "response_contract": state.llm_prompt.response_contract,
        "metadata": state.llm_prompt.metadata,
    }
    return {"input": json.dumps(payload, sort_keys=True)}


def _tool_schema_for_prompt(state: AssistantState, available_tools: list[str]) -> list[dict[str, object]]:
    if state.bound_tools:
        bound_tools = state.bound_tools
    elif state.llm_prompt is not None:
        bound_tools = {
            tool.name: type(
                "PromptTool",
                (),
                {
                    "capability_name": tool.name,
                    "description": tool.description,
                    "provider_input_schema": tool.input_schema,
                },
            )()
            for tool in state.llm_prompt.tools
        }
    else:
        return []
    schemas: list[dict[str, object]] = []
    for name in available_tools:
        tool = bound_tools.get(name)
        if tool is None:
            continue
        schemas.append(
            {
                "type": "function",
                "name": tool.capability_name,
                "description": tool.description,
                "parameters": tool.provider_input_schema,
            }
        )
    return schemas


def _coerce_text(response: dict[str, object]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str):
        return output_text
    outputs = response.get("output", [])
    if isinstance(outputs, list):
        texts: list[str] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    texts.append(block["text"])
        return "\n".join(part for part in texts if part).strip()
    return ""


@dataclass
class ProviderBackedModelAdapter(ModelAdapter):
    settings: Settings
    client: ProviderClient | None = None
    _default_client: ProviderClient = field(init=False, repr=False)
    _base_retry_delay_seconds: float = field(default=1.0, init=False, repr=False)
    _max_retry_delay_seconds: float = field(default=16.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._default_client = OpenAIResponsesClient()

    def runtime_services(self) -> ToolRuntimeServices:
        return ToolRuntimeServices()

    def _retry_delay_seconds(self, *, attempt_number: int) -> float:
        delay = min(self._max_retry_delay_seconds, self._base_retry_delay_seconds * (2 ** max(attempt_number - 1, 0)))
        jitter = random.uniform(0.0, 0.25 * delay)
        return delay + jitter

    def complete_turn(self, *, state: AssistantState, available_tools: list[str]) -> ModelTurnResult:
        prompt = _serialize_prompt(state)
        tool_mode = "none" if self.settings.llm_disable_tools else self.settings.llm_tool_call_mode
        tools = [] if tool_mode == "none" else _tool_schema_for_prompt(state, available_tools)
        client = self.client or self._default_client

        attempts = 0
        while True:
            attempts += 1
            try:
                response = client.create_response(prompt=prompt, tools=tools, settings=self.settings)
                return self._translate_response(
                    response=response,
                    available_tools=available_tools,
                    tool_mode=tool_mode,
                    attempts=attempts,
                    state=state,
                )
            except ProviderError as exc:
                if exc.retryable and attempts <= self.settings.llm_max_retries:
                    time.sleep(self._retry_delay_seconds(attempt_number=attempts))
                    continue
                raise

    def stream_final_answer(self, *, state: AssistantState, available_tools: list[str]) -> tuple[list[str], ModelTurnResult]:
        result = self.complete_turn(state=state, available_tools=available_tools)
        if result.needs_tools:
            return [], result
        text = result.response_text
        deltas = [text[index : index + 24] for index in range(0, len(text), 24)] if text else []
        return deltas, result

    def _translate_response(
        self,
        *,
        response: dict[str, object],
        available_tools: list[str],
        tool_mode: str,
        attempts: int,
        state: AssistantState,
    ) -> ModelTurnResult:
        output = response.get("output", [])
        if output is not None and not isinstance(output, list):
            raise ProviderError(
                category="provider_malformed_response",
                retryable=False,
                detail="provider output was not a list",
            )

        tool_requests: list[ToolRequest] = []
        rejected_tool_requests: list[RejectedToolRequest] = []
        semantic_fallback_kind: str | None = None

        for item in output or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type not in {"function_call", "tool_call"}:
                continue

            raw_name = item.get("name")
            raw_call_id = item.get("call_id") or item.get("id") or str(uuid4())
            raw_arguments = item.get("arguments", {})

            if not isinstance(raw_name, str):
                semantic_fallback_kind = "malformed_tool_payload"
                continue
            if raw_name not in available_tools:
                rejected_tool_requests.append(
                    RejectedToolRequest(
                        correlation_id=str(raw_call_id),
                        capability_name=raw_name,
                        arguments={},
                        error="tool not available in runtime context",
                    )
                )
                semantic_fallback_kind = "rejected_tool_request"
                continue
            if len(tool_requests) >= self.settings.llm_max_tool_requests_per_turn:
                rejected_tool_requests.append(
                    RejectedToolRequest(
                        correlation_id=str(raw_call_id),
                        capability_name=raw_name,
                        arguments={},
                        error="tool request limit exceeded",
                    )
                )
                semantic_fallback_kind = "rejected_tool_request"
                continue

            arguments: object = raw_arguments
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = None
            if not isinstance(arguments, dict):
                rejected_tool_requests.append(
                    RejectedToolRequest(
                        correlation_id=str(raw_call_id),
                        capability_name=raw_name,
                        arguments={},
                        error="tool arguments must be a JSON object",
                    )
                )
                semantic_fallback_kind = "rejected_tool_request"
                continue
            tool_requests.append(
                ToolRequest(
                    correlation_id=str(raw_call_id),
                    capability_name=raw_name,
                    arguments=arguments,
                    metadata={"source": "provider"},
                )
            )

        response_text = _coerce_text(response)
        if not tool_requests and rejected_tool_requests and not response_text:
            response_text = "I could not safely use the requested tool output from the model."

        return ModelTurnResult(
            needs_tools=bool(tool_requests),
            tool_requests=tool_requests,
            response_text=response_text,
            execution_metadata={
                "provider_name": self.settings.llm_provider,
                "model_name": self.settings.llm_model,
                "prompt_strategy_id": state.llm_prompt.metadata["prompt_strategy_id"] if state.llm_prompt else "provider-runtime-v1",
                "tool_call_mode": tool_mode,
                "provider_attempt_count": attempts,
                "semantic_fallback_kind": semantic_fallback_kind,
            },
            rejected_tool_requests=rejected_tool_requests,
        )
