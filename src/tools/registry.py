from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from src.graphs.state import ToolResultPayload, ToolRuntimeContext, ToolValidationIssue
from src.policies.service import PolicyService
from src.tools.typed_actions import get_typed_action


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSchemaValidationError(ValueError):
    capability_name: str
    code: str
    message: str
    issues: list[ToolValidationIssue]

    def __str__(self) -> str:
        return self.message


def validation_error_from_pydantic(*, capability_name: str, exc: ValidationError) -> ToolSchemaValidationError:
    issues: list[ToolValidationIssue] = []
    for issue in exc.errors():
        field_path = ".".join(str(part) for part in issue.get("loc", ())) or "<root>"
        issues.append(
            ToolValidationIssue(
                field_path=field_path,
                message=issue.get("msg", "invalid value"),
            )
        )
    return ToolSchemaValidationError(
        capability_name=capability_name,
        code="invalid_tool_arguments",
        message=f"Invalid arguments for `{capability_name}`.",
        issues=issues,
    )


@dataclass(frozen=True)
class ToolDefinition:
    capability_name: str
    description: str
    invoke: Callable[[Any], ToolResultPayload]
    input_schema: type[BaseModel] | None = None
    tool_schema_name: str = ""
    schema_version: str = "1.0"
    usage_guidance: str = ""
    provider_input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": True}
    )
    validate: Callable[[dict[str, Any]], Any] | None = None
    canonicalize: Callable[[Any], dict[str, Any]] | None = None

    @property
    def typed_action_id(self) -> str | None:
        typed_action = get_typed_action(self.capability_name)
        return None if typed_action is None else typed_action.typed_action_id

    @property
    def requires_approval(self) -> bool:
        typed_action = get_typed_action(self.capability_name)
        return bool(typed_action and typed_action.requires_approval)

    def validate_arguments(self, arguments: dict[str, Any]) -> Any:
        if self.validate is None:
            return arguments
        return self.validate(arguments)

    def canonicalize_arguments(self, validated: Any) -> dict[str, Any]:
        if self.canonicalize is None:
            if isinstance(validated, dict):
                return validated
            raise ToolExecutionError(f"tool `{self.capability_name}` is missing canonicalization support")
        return self.canonicalize(validated)


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
