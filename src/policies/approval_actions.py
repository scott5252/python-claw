from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.agents.service import AgentProfileService
from src.capabilities.activation import ActivationController
from src.config.settings import Settings
from src.db.models import ApprovalActionPromptStatus
from src.delegations.repository import DelegationRepository
from src.jobs.repository import JobsRepository
from src.sessions.repository import SessionRepository


@dataclass
class ApprovalDecisionResult:
    proposal_id: str
    decision: str
    outcome: str
    prompt_id: int | None = None
    approval_id: str | None = None
    continuation_enqueued: bool = False
    continuation_run_id: str | None = None
    continuation_session_id: str | None = None
    continuation_agent_id: str | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_token(token: str) -> str:
    normalized = token.strip()
    try:
        parsed = json.loads(normalized)
        if isinstance(parsed, str):
            normalized = parsed.strip()
    except Exception:
        pass
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
        normalized = normalized[1:-1].strip()
    return normalized


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class ApprovalDecisionService:
    repository: SessionRepository
    activation_controller: ActivationController
    settings: Settings
    jobs_repository: JobsRepository | None = None
    delegation_repository: DelegationRepository | None = None
    agent_profile_service: AgentProfileService | None = None

    def materialize_prompt_for_session(
        self,
        db: Session,
        *,
        proposal_id: str,
        session_id: str,
        agent_id: str,
        message_id: int,
        channel_kind: str,
        channel_account_id: str,
        transport_address_key: str | None,
        canonical_prompt: dict[str, object],
    ) -> tuple[object, dict[str, str]]:
        approve_token = secrets.token_urlsafe(24)
        deny_token = secrets.token_urlsafe(24)
        prompt = self.repository.create_approval_action_prompt(
            db,
            proposal_id=proposal_id,
            session_id=session_id,
            agent_id=agent_id,
            message_id=message_id,
            channel_kind=channel_kind,
            channel_account_id=channel_account_id,
            transport_address_key=transport_address_key,
            approve_token_hash=hash_token(approve_token),
            deny_token_hash=hash_token(deny_token),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.settings.approval_action_token_ttl_seconds),
            presentation_payload={
                **canonical_prompt,
                "actions": {
                    "approve": {"decision": "approve", "token": approve_token},
                    "deny": {"decision": "deny", "token": deny_token},
                },
            },
        )
        self.repository.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="approval_prompt_rendered",
            proposal_id=proposal_id,
            approval_prompt_id=prompt.id,
            payload={
                "channel_kind": channel_kind,
                "channel_account_id": channel_account_id,
                "transport_address_key": transport_address_key,
            },
        )
        return prompt, {"approve_token": approve_token, "deny_token": deny_token}

    def decide(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int | None,
        actor_id: str,
        decision: str,
        proposal_id: str | None = None,
        token: str | None = None,
        decided_via: str,
    ) -> ApprovalDecisionResult:
        prompt = None
        if token:
            normalized_token = normalize_token(token)
            prompt = self.repository.get_approval_action_prompt_by_hash(
                db,
                token_hash=hash_token(normalized_token),
                decision=decision,
            )
            if prompt is None:
                raise LookupError("approval prompt not found")
            if prompt.status != ApprovalActionPromptStatus.PENDING.value:
                return ApprovalDecisionResult(
                    proposal_id=prompt.proposal_id,
                    decision=decision,
                    outcome=prompt.status,
                    prompt_id=prompt.id,
                )
            if normalize_datetime(prompt.expires_at) < datetime.now(timezone.utc):
                prompt.status = ApprovalActionPromptStatus.EXPIRED.value
                prompt.updated_at = datetime.now(timezone.utc)
                db.flush()
                return ApprovalDecisionResult(
                    proposal_id=prompt.proposal_id,
                    decision=decision,
                    outcome="expired",
                    prompt_id=prompt.id,
                )
            proposal_id = prompt.proposal_id
        if not proposal_id:
            raise ValueError("proposal_id or token is required")
        proposal = self.repository.get_pending_proposal(db, proposal_id=proposal_id) or self.repository.get_proposal(db, proposal_id=proposal_id)
        if proposal is None:
            raise LookupError("proposal not found")
        resolved_message_id = message_id or proposal.message_id
        resolved_session_id = proposal.session_id
        if decision == "approve":
            approval = self.repository.approve_proposal(
                db,
                session_id=resolved_session_id,
                message_id=resolved_message_id,
                proposal_id=proposal_id,
                approver_id=actor_id,
            )
            active, _ = self.repository.activate_approved_resource(
                db,
                proposal_id=approval.proposal_id,
                resource_version_id=approval.resource_version_id,
                typed_action_id=approval.typed_action_id,
                canonical_params_hash=approval.canonical_params_hash,
            )
            self.repository.mark_approval_prompt_decision(
                db,
                proposal_id=proposal_id,
                prompt=prompt,
                status=ApprovalActionPromptStatus.APPROVED.value,
                decided_via=decided_via,
                decider_actor_id=actor_id,
            )
            continuation = self._enqueue_approved_continuation(
                db,
                proposal_id=proposal_id,
                actor_id=actor_id,
            )
            return ApprovalDecisionResult(
                proposal_id=proposal_id,
                decision=decision,
                outcome="approved",
                prompt_id=None if prompt is None else prompt.id,
                approval_id=approval.id,
                continuation_enqueued=continuation["enqueued"],
                continuation_run_id=continuation["run_id"],
                continuation_session_id=continuation["session_id"],
                continuation_agent_id=continuation["agent_id"],
            )
        self.repository.deny_proposal(
            db,
            session_id=resolved_session_id,
            message_id=resolved_message_id,
            proposal_id=proposal_id,
            approver_id=actor_id,
        )
        self.repository.mark_approval_prompt_decision(
            db,
            proposal_id=proposal_id,
            prompt=prompt,
            status=ApprovalActionPromptStatus.DENIED.value,
            decided_via=decided_via,
            decider_actor_id=actor_id,
        )
        return ApprovalDecisionResult(
            proposal_id=proposal_id,
            decision=decision,
            outcome="denied",
            prompt_id=None if prompt is None else prompt.id,
        )

    def _enqueue_approved_continuation(
        self,
        db: Session,
        *,
        proposal_id: str,
        actor_id: str,
    ) -> dict[str, str | bool | None]:
        if (
            self.jobs_repository is None
            or self.delegation_repository is None
            or self.agent_profile_service is None
        ):
            return {"enqueued": False, "run_id": None, "session_id": None, "agent_id": None}

        proposal = self.repository.get_proposal(db, proposal_id=proposal_id)
        if proposal is None:
            return {"enqueued": False, "run_id": None, "session_id": None, "agent_id": None}
        session = self.repository.get_session(db, proposal.session_id)
        if session is None or session.session_kind != "child":
            return {"enqueued": False, "run_id": None, "session_id": None, "agent_id": None}
        delegation = self.delegation_repository.get_by_child_session(db, child_session_id=session.id)
        if delegation is None:
            return {"enqueued": False, "run_id": None, "session_id": None, "agent_id": None}

        packet = self.repository.get_proposal_packet(db, proposal_id=proposal_id)
        if packet is None:
            return {"enqueued": False, "run_id": None, "session_id": None, "agent_id": None}
        try:
            approved_arguments = json.loads(packet["canonical_params_json"])
        except Exception:
            approved_arguments = {}

        continuation_text = self._build_child_approval_continuation_message(
            proposal_id=proposal_id,
            capability_name=str(packet["capability_name"]),
            approved_arguments=approved_arguments,
        )
        continuation_message = self.repository.append_message(
            db,
            session,
            role="system",
            content=continuation_text,
            external_message_id=None,
            sender_id=f"system:approval:{actor_id}",
            last_activity_at=datetime.now(timezone.utc),
        )
        binding = self.agent_profile_service.resolve_binding_for_session(db, session=session)
        run = self.jobs_repository.create_or_get_execution_run(
            db,
            session_id=session.id,
            message_id=continuation_message.id,
            agent_id=binding.agent_id,
            model_profile_key=binding.model_profile_key,
            policy_profile_key=binding.policy_profile_key,
            tool_profile_key=binding.tool_profile_key,
            trigger_kind="delegation_child",
            trigger_ref=f"{delegation.id}:approved:{proposal_id}",
            lane_key=session.id,
            max_attempts=self.settings.execution_run_max_attempts,
        )
        self.delegation_repository.requeue_child_run(
            db,
            delegation_id=delegation.id,
            child_message_id=continuation_message.id,
            child_run_id=run.id,
        )
        self.delegation_repository.append_event(
            db,
            delegation_id=delegation.id,
            event_kind="approved_continuation_queued",
            status="queued",
            actor_kind="system",
            actor_ref=proposal_id,
            payload={
                "proposal_id": proposal_id,
                "child_run_id": run.id,
                "child_message_id": continuation_message.id,
            },
        )
        return {
            "enqueued": True,
            "run_id": run.id,
            "session_id": session.id,
            "agent_id": binding.agent_id,
        }

    def _build_child_approval_continuation_message(
        self,
        *,
        proposal_id: str,
        capability_name: str,
        approved_arguments: dict[str, object],
    ) -> str:
        arguments_json = json.dumps(approved_arguments, indent=2, sort_keys=True)
        return "\n".join(
            [
                f"Approval was granted for proposal `{proposal_id}`.",
                "",
                f"Continue the pending `{capability_name}` action now.",
                "Use the exact approved tool arguments below.",
                "Do not ask for another approval, do not create a new proposal, and do not delegate again.",
                "",
                "Approved arguments:",
                arguments_json,
                "",
                f"Your next response should be the `{capability_name}` tool request using those exact arguments.",
            ]
        )
