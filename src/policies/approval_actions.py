from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from src.capabilities.activation import ActivationController
from src.config.settings import Settings
from src.db.models import ApprovalActionPromptStatus
from src.sessions.repository import SessionRepository


@dataclass
class ApprovalDecisionResult:
    proposal_id: str
    decision: str
    outcome: str
    prompt_id: int | None = None
    approval_id: str | None = None


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
            return ApprovalDecisionResult(
                proposal_id=proposal_id,
                decision=decision,
                outcome="approved",
                prompt_id=None if prompt is None else prompt.id,
                approval_id=approval.id,
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
