from __future__ import annotations

from dataclasses import dataclass, field

from src.graphs.state import ToolRuntimeContext


@dataclass
class PolicyService:
    denied_capabilities: set[str] = field(default_factory=set)

    def is_tool_allowed(self, *, context: ToolRuntimeContext, capability_name: str) -> bool:
        _ = context
        return capability_name not in self.denied_capabilities
