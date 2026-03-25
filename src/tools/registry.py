from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.graphs.state import ToolResultPayload, ToolRuntimeContext
from src.policies.service import PolicyService


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    capability_name: str
    description: str
    invoke: Callable[[dict[str, Any]], ToolResultPayload]


ToolFactory = Callable[[ToolRuntimeContext], ToolDefinition]


@dataclass
class ToolRegistry:
    factories: dict[str, ToolFactory]

    def bind_tools(
        self,
        *,
        context: ToolRuntimeContext,
        policy_service: PolicyService,
    ) -> dict[str, ToolDefinition]:
        bound: dict[str, ToolDefinition] = {}
        for capability_name, factory in self.factories.items():
            if not policy_service.is_tool_visible(context=context, capability_name=capability_name):
                continue
            bound[capability_name] = factory(context)
        return bound
