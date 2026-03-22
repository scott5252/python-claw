from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class ActivationResult:
    active_resource_id: str
    activation_state: str
    created: bool


@dataclass
class ActivationController:
    repository: any

    def activate(
        self,
        db: Session,
        *,
        session_id: str,
        message_id: int,
        proposal_id: str,
        resource_version_id: str,
        typed_action_id: str,
        canonical_params_hash: str,
    ) -> ActivationResult:
        active_resource, created = self.repository.activate_approved_resource(
            db,
            proposal_id=proposal_id,
            resource_version_id=resource_version_id,
            typed_action_id=typed_action_id,
            canonical_params_hash=canonical_params_hash,
        )
        self.repository.append_governance_event(
            db,
            session_id=session_id,
            message_id=message_id,
            event_kind="activation_result",
            proposal_id=proposal_id,
            resource_version_id=resource_version_id,
            active_resource_id=active_resource.id,
            payload={
                "typed_action_id": typed_action_id,
                "canonical_params_hash": canonical_params_hash,
                "activation_state": active_resource.activation_state,
                "created": created,
            },
        )
        return ActivationResult(
            active_resource_id=active_resource.id,
            activation_state=active_resource.activation_state,
            created=created,
        )
