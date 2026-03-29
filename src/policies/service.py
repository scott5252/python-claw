from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.graphs.state import ToolRuntimeContext, ValidatedToolCall
from src.tools.typed_actions import get_typed_action


def default_tool_schema_identity(capability_name: str) -> tuple[str, str]:
    if capability_name == "remote_exec":
        return "remote_exec.invocation", "1.0"
    return f"{capability_name}.input", "1.0"


def canonicalize_params(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonicalize_tool_arguments(*, tool: Any, arguments: dict[str, Any]) -> tuple[Any, dict[str, Any], str]:
    validated = tool.validate_arguments(arguments)
    canonical_arguments = tool.canonicalize_arguments(validated)
    canonical_arguments_json = canonicalize_params(canonical_arguments)
    return validated, canonical_arguments, canonical_arguments_json


def build_approval_identity_payload(
    *,
    tool_schema_name: str,
    tool_schema_version: str,
    canonical_arguments_json: str,
) -> str:
    return canonicalize_params(
        {
            "tool_schema_name": tool_schema_name,
            "tool_schema_version": tool_schema_version,
            "canonical_arguments_json": canonical_arguments_json,
        }
    )


def build_approval_identity_hash(
    *,
    tool_schema_name: str,
    tool_schema_version: str,
    canonical_arguments_json: str,
) -> str:
    return hash_payload(
        build_approval_identity_payload(
            tool_schema_name=tool_schema_name,
            tool_schema_version=tool_schema_version,
            canonical_arguments_json=canonical_arguments_json,
        )
    )


@dataclass(frozen=True)
class ApprovalMatch:
    proposal_id: str
    resource_version_id: str
    content_hash: str
    typed_action_id: str
    tool_schema_name: str
    tool_schema_version: str
    canonical_params_json: str
    canonical_params_hash: str
    approval_id: str
    active_resource_id: str


@dataclass(frozen=True)
class TurnClassification:
    request_class: str
    capability_name: str | None = None
    typed_action_id: str | None = None
    arguments: dict[str, Any] | None = None
    proposal_id: str | None = None


@dataclass
class PolicyService:
    denied_capabilities: set[str] = field(default_factory=set)
    remote_execution_enabled: bool = False
    allowed_capabilities: set[str] | None = None
    policy_profile_key: str = ""
    tool_profile_key: str = ""
    delegation_enabled: bool = False
    max_delegation_depth: int = 0
    allowed_child_agent_ids: set[str] = field(default_factory=set)
    max_active_delegations_per_run: int | None = None
    max_active_delegations_per_session: int | None = None

    def classify_turn(self, *, user_text: str) -> TurnClassification:
        lowered = user_text.strip().lower()
        if lowered.startswith("send "):
            return TurnClassification(
                request_class="execute_action",
                capability_name="send_message",
                typed_action_id="tool.send_message",
                arguments={"text": user_text.strip()[5:]},
            )
        if lowered.startswith("approve "):
            return TurnClassification(
                request_class="approval_decision",
                proposal_id=user_text.strip()[8:].strip(),
            )
        if lowered.startswith("revoke "):
            return TurnClassification(
                request_class="revocation",
                proposal_id=user_text.strip()[7:].strip(),
            )
        return TurnClassification(request_class="answer_only")

    def approval_lookup_key(
        self,
        *,
        capability_name: str,
        tool_schema_name: str | None = None,
        tool_schema_version: str | None = None,
        canonical_arguments_json: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, str] | None:
        typed_action = get_typed_action(capability_name)
        if typed_action is None or not typed_action.requires_approval:
            return None
        legacy_shape = tool_schema_name is None and tool_schema_version is None and canonical_arguments_json is None and arguments is not None
        resolved_schema_name, resolved_schema_version = default_tool_schema_identity(capability_name)
        if tool_schema_name is None:
            tool_schema_name = resolved_schema_name
        if tool_schema_version is None:
            tool_schema_version = resolved_schema_version
        if canonical_arguments_json is None:
            canonical_arguments_json = canonicalize_params(arguments or {})
        if legacy_shape:
            return typed_action.typed_action_id, build_approval_identity_hash(
                tool_schema_name=tool_schema_name,
                tool_schema_version=tool_schema_version,
                canonical_arguments_json=canonical_arguments_json,
            )
        return (
            typed_action.typed_action_id,
            tool_schema_name,
            tool_schema_version,
            build_approval_identity_hash(
                tool_schema_name=tool_schema_name,
                tool_schema_version=tool_schema_version,
                canonical_arguments_json=canonical_arguments_json,
            ),
        )

    def approval_lookup_key_for_call(self, *, call: ValidatedToolCall) -> tuple[str, str, str, str] | None:
        return self.approval_lookup_key(
            capability_name=call.capability_name,
            tool_schema_name=call.tool_schema_name,
            tool_schema_version=call.schema_version,
            canonical_arguments_json=call.canonical_arguments_json,
        )

    def build_policy_context(
        self,
        db: Session,
        *,
        repository: Any,
        session_id: str,
        agent_id: str,
        user_text: str,
    ) -> dict[str, Any]:
        classification = self.classify_turn(user_text=user_text)
        approvals = repository.list_active_approvals(
            db,
            session_id=session_id,
            agent_id=agent_id,
            now=datetime.now(timezone.utc),
        )
        if not approvals:
            approvals = repository.replay_active_approvals(
                db,
                session_id=session_id,
                agent_id=agent_id,
                now=datetime.now(timezone.utc),
            )
        approval_map = {
            (
                approval["capability_name"],
                approval["typed_action_id"],
                approval["tool_schema_name"],
                approval["tool_schema_version"],
                approval["canonical_params_hash"],
            ): approval
            for approval in approvals
        }
        return {
            "classification": classification,
            "approval_map": approval_map,
            "active_approvals": approvals,
        }

    def is_tool_visible(self, *, context: ToolRuntimeContext, capability_name: str) -> bool:
        _ = context
        if self.allowed_capabilities is not None and capability_name not in self.allowed_capabilities:
            return False
        if capability_name in self.denied_capabilities:
            return False
        if capability_name == "remote_exec" and not self.remote_execution_enabled:
            return False

        typed_action = get_typed_action(capability_name)
        return typed_action is not None

    def is_tool_allowed(self, *, context: ToolRuntimeContext, capability_name: str) -> bool:
        return self.is_tool_visible(context=context, capability_name=capability_name)

    def assert_delegation_allowed(
        self,
        *,
        context: ToolRuntimeContext,
        child_agent_id: str,
        depth: int,
        active_delegations_for_run: int,
        active_delegations_for_session: int,
    ) -> None:
        if not self.is_tool_visible(context=context, capability_name="delegate_to_agent"):
            raise PermissionError("delegation tool not available in runtime context")
        if not self.delegation_enabled:
            raise PermissionError("delegation is disabled for this policy profile")
        if child_agent_id not in self.allowed_child_agent_ids:
            raise PermissionError("requested child agent is not allowlisted")
        if depth > self.max_delegation_depth:
            raise PermissionError("delegation depth exceeds configured maximum")
        if (
            self.max_active_delegations_per_run is not None
            and active_delegations_for_run >= self.max_active_delegations_per_run
        ):
            raise PermissionError("active delegation limit reached for run")
        if (
            self.max_active_delegations_per_session is not None
            and active_delegations_for_session >= self.max_active_delegations_per_session
        ):
            raise PermissionError("active delegation limit reached for session")

    def has_exact_approval(
        self,
        *,
        context: ToolRuntimeContext,
        call: ValidatedToolCall | None = None,
        capability_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> bool:
        return self.get_matching_approval(
            context=context,
            call=call,
            capability_name=capability_name,
            arguments=arguments,
        ) is not None

    def get_matching_approval(
        self,
        *,
        context: ToolRuntimeContext,
        call: ValidatedToolCall | None = None,
        capability_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> ApprovalMatch | None:
        if call is None:
            if capability_name is None:
                return None
            schema_name, schema_version = default_tool_schema_identity(capability_name)
            approval_key = self.approval_lookup_key(
                capability_name=capability_name,
                tool_schema_name=schema_name,
                tool_schema_version=schema_version,
                arguments=arguments or {},
            )
            lookup_capability_name = capability_name
            legacy_canonical_hash = hash_payload(canonicalize_params(arguments or {}))
        else:
            approval_key = self.approval_lookup_key_for_call(call=call)
            lookup_capability_name = call.capability_name
            legacy_canonical_hash = hash_payload(call.canonical_arguments_json)
        if approval_key is None:
            return None
        typed_action_id, tool_schema_name, tool_schema_version, canonical_params_hash = approval_key
        approval = context.policy_context.get("approval_map", {}).get(
            (lookup_capability_name, typed_action_id, tool_schema_name, tool_schema_version, canonical_params_hash)
        )
        if approval is None:
            approval = context.policy_context.get("approval_map", {}).get(
                (lookup_capability_name, typed_action_id, canonical_params_hash)
            )
        if approval is None:
            approval = context.policy_context.get("approval_map", {}).get(
                (lookup_capability_name, typed_action_id, legacy_canonical_hash)
            )
        if approval is None:
            return None
        resolved_schema_name = approval.get("tool_schema_name", tool_schema_name)
        resolved_schema_version = approval.get("tool_schema_version", tool_schema_version)
        return ApprovalMatch(
            proposal_id=approval["proposal_id"],
            resource_version_id=approval["resource_version_id"],
            content_hash=approval["content_hash"],
            typed_action_id=approval["typed_action_id"],
            tool_schema_name=resolved_schema_name,
            tool_schema_version=resolved_schema_version,
            canonical_params_json=approval["canonical_params_json"],
            canonical_params_hash=approval["canonical_params_hash"],
            approval_id=approval["approval_id"],
            active_resource_id=approval["active_resource_id"],
        )

    def assert_execution_allowed(
        self,
        *,
        context: ToolRuntimeContext,
        call: ValidatedToolCall | None = None,
        capability_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> ApprovalMatch | None:
        lookup_capability_name = call.capability_name if call is not None else capability_name
        if lookup_capability_name is None:
            raise PermissionError("capability not registered")
        if lookup_capability_name in self.denied_capabilities:
            raise PermissionError("capability denied by policy")

        typed_action = get_typed_action(lookup_capability_name)
        if typed_action is None:
            raise PermissionError("capability not registered")
        if not typed_action.requires_approval:
            return None

        approval = self.get_matching_approval(
            context=context,
            call=call,
            capability_name=capability_name,
            arguments=arguments,
        )
        if approval is None:
            raise PermissionError("missing exact approval for requested action")
        return approval
