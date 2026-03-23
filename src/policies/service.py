from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.graphs.state import ToolRuntimeContext
from src.tools.typed_actions import get_typed_action


def canonicalize_params(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalMatch:
    proposal_id: str
    resource_version_id: str
    content_hash: str
    typed_action_id: str
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

    def approval_lookup_key(self, *, capability_name: str, arguments: dict[str, Any]) -> tuple[str, str] | None:
        typed_action = get_typed_action(capability_name)
        if typed_action is None or not typed_action.requires_approval:
            return None
        canonical_params_json = canonicalize_params(arguments)
        return typed_action.typed_action_id, hash_payload(canonical_params_json)

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
                approval["canonical_params_hash"],
            ): approval
            for approval in approvals
        }
        return {
            "classification": classification,
            "approval_map": approval_map,
            "active_approvals": approvals,
        }

    def is_tool_allowed(self, *, context: ToolRuntimeContext, capability_name: str) -> bool:
        if capability_name in self.denied_capabilities:
            return False

        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            return False
        if not typed_action.requires_approval:
            return True

        classification: TurnClassification | None = context.policy_context.get("classification")
        if classification is None or classification.capability_name != capability_name or classification.arguments is None:
            return False
        approval_key = self.approval_lookup_key(
            capability_name=capability_name,
            arguments=classification.arguments,
        )
        if approval_key is None:
            return False
        typed_action_id, canonical_params_hash = approval_key
        approval = context.policy_context.get("approval_map", {}).get(
            (capability_name, typed_action_id, canonical_params_hash)
        )
        return approval is not None

    def get_matching_approval(
        self,
        *,
        context: ToolRuntimeContext,
        capability_name: str,
        arguments: dict[str, Any],
    ) -> ApprovalMatch | None:
        approval_key = self.approval_lookup_key(capability_name=capability_name, arguments=arguments)
        if approval_key is None:
            return None
        typed_action_id, canonical_params_hash = approval_key
        approval = context.policy_context.get("approval_map", {}).get(
            (capability_name, typed_action_id, canonical_params_hash)
        )
        if approval is None:
            return None
        return ApprovalMatch(
            proposal_id=approval["proposal_id"],
            resource_version_id=approval["resource_version_id"],
            content_hash=approval["content_hash"],
            typed_action_id=approval["typed_action_id"],
            canonical_params_json=approval["canonical_params_json"],
            canonical_params_hash=approval["canonical_params_hash"],
            approval_id=approval["approval_id"],
            active_resource_id=approval["active_resource_id"],
        )

    def assert_execution_allowed(
        self,
        *,
        context: ToolRuntimeContext,
        capability_name: str,
        arguments: dict[str, Any],
    ) -> ApprovalMatch | None:
        if capability_name in self.denied_capabilities:
            raise PermissionError("capability denied by policy")

        typed_action = get_typed_action(capability_name)
        if typed_action is None:
            raise PermissionError("capability not registered")
        if not typed_action.requires_approval:
            return None

        approval = self.get_matching_approval(
            context=context,
            capability_name=capability_name,
            arguments=arguments,
        )
        if approval is None:
            raise PermissionError("missing exact approval for requested action")
        return approval
