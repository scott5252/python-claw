from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.graphs.prompts import render_prompt
from src.graphs.state import AssistantState, ToolEvent, ToolRuntimeContext
from src.observability.audit import ToolAuditEvent
from src.policies.service import ApprovalMatch, TurnClassification
from src.tools.registry import ToolRegistry


@dataclass
class GraphDependencies:
    repository: Any
    policy_service: Any
    model: Any
    tool_registry: ToolRegistry
    audit_sink: Any
    activation_controller: Any
    transcript_context_limit: int


def assemble_state(
    *,
    db: Session,
    dependencies: GraphDependencies,
    session_id: str,
    message_id: int,
    agent_id: str,
    channel_kind: str,
    sender_id: str,
    user_text: str,
) -> AssistantState:
    messages = dependencies.repository.list_conversation_messages(
        db,
        session_id=session_id,
        limit=dependencies.transcript_context_limit,
    )
    return AssistantState(
        session_id=session_id,
        message_id=message_id,
        agent_id=agent_id,
        channel_kind=channel_kind,
        sender_id=sender_id,
        user_text=user_text,
        messages=messages,
    )


def _build_context(*, state: AssistantState, dependencies: GraphDependencies, db: Session) -> ToolRuntimeContext:
    policy_context = dependencies.policy_service.build_policy_context(
        db,
        repository=dependencies.repository,
        session_id=state.session_id,
        agent_id=state.agent_id,
        user_text=state.user_text,
    )
    policy_context["prompt"] = render_prompt(state)
    return ToolRuntimeContext(
        session_id=state.session_id,
        message_id=state.message_id,
        agent_id=state.agent_id,
        channel_kind=state.channel_kind,
        sender_id=state.sender_id,
        policy_context=policy_context,
        runtime_services=dependencies.model.runtime_services(),
    )


def _record_governance_audit(
    *,
    db: Session,
    dependencies: GraphDependencies,
    session_id: str,
    correlation_id: str,
    capability_name: str,
    event_kind: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    dependencies.audit_sink.record(
        db,
        ToolAuditEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            capability_name=capability_name,
            event_kind=event_kind,
            status=status,
            payload=payload,
        ),
    )


def _handle_approval_decision(
    *,
    db: Session,
    state: AssistantState,
    dependencies: GraphDependencies,
    classification: TurnClassification,
) -> AssistantState:
    proposal_id = classification.proposal_id or ""
    pending = dependencies.repository.get_pending_proposal(db, proposal_id=proposal_id)
    if pending is None:
        state.response_text = f"No pending proposal found for `{proposal_id}`."
        return state

    approval = dependencies.repository.approve_proposal(
        db,
        session_id=state.session_id,
        message_id=state.message_id,
        proposal_id=proposal_id,
        approver_id=state.sender_id,
    )
    activation = dependencies.activation_controller.activate(
        db,
        session_id=state.session_id,
        message_id=state.message_id,
        proposal_id=approval.proposal_id,
        resource_version_id=approval.resource_version_id,
        typed_action_id=approval.typed_action_id,
        canonical_params_hash=approval.canonical_params_hash,
    )
    packet = dependencies.repository.get_proposal_packet(db, proposal_id=proposal_id)
    _record_governance_audit(
        db=db,
        dependencies=dependencies,
        session_id=state.session_id,
        correlation_id=proposal_id,
        capability_name=packet["capability_name"],
        event_kind="approval_decision",
        status="approved",
        payload={
            "proposal_id": proposal_id,
            "resource_version_id": approval.resource_version_id,
            "approval_id": approval.id,
            "active_resource_id": activation.active_resource_id,
            "typed_action_id": approval.typed_action_id,
            "canonical_params_hash": approval.canonical_params_hash,
            "approver_id": state.sender_id,
        },
    )
    state.response_text = (
        f"Approved proposal `{proposal_id}` for `{packet['capability_name']}`. "
        "Retry the original request to use the newly active capability."
    )
    return state


def _handle_revocation(
    *,
    db: Session,
    state: AssistantState,
    dependencies: GraphDependencies,
    classification: TurnClassification,
) -> AssistantState:
    proposal_id = classification.proposal_id or ""
    revoked = dependencies.repository.revoke_proposal(
        db,
        session_id=state.session_id,
        message_id=state.message_id,
        proposal_id=proposal_id,
        revoked_by=state.sender_id,
        reason="user_requested",
    )
    if not revoked:
        state.response_text = f"No proposal found for `{proposal_id}`."
        return state
    packet = dependencies.repository.get_proposal_packet(db, proposal_id=proposal_id)
    capability_name = packet["capability_name"] if packet is not None else "governance"
    _record_governance_audit(
        db=db,
        dependencies=dependencies,
        session_id=state.session_id,
        correlation_id=proposal_id,
        capability_name=capability_name,
        event_kind="revocation_result",
        status="revoked",
        payload={"proposal_id": proposal_id, "revoked_by": state.sender_id},
    )
    state.response_text = f"Revoked proposal `{proposal_id}`."
    return state


def _handle_awaiting_approval(
    *,
    db: Session,
    state: AssistantState,
    dependencies: GraphDependencies,
    classification: TurnClassification,
) -> AssistantState:
    capability_name = classification.capability_name or "unknown"
    arguments = classification.arguments or {}
    proposal, version = dependencies.repository.create_governance_proposal(
        db,
        session_id=state.session_id,
        message_id=state.message_id,
        agent_id=state.agent_id,
        requested_by=state.sender_id,
        capability_name=capability_name,
        arguments=arguments,
    )
    packet = dependencies.repository.get_proposal_packet(db, proposal_id=proposal.id)
    _record_governance_audit(
        db=db,
        dependencies=dependencies,
        session_id=state.session_id,
        correlation_id=proposal.id,
        capability_name=capability_name,
        event_kind="approval_requested",
        status="pending_approval",
        payload={
            "proposal_id": proposal.id,
            "resource_version_id": version.id,
            "content_hash": version.content_hash,
            "typed_action_id": packet["typed_action_id"],
            "canonical_params_hash": packet["canonical_params_hash"],
        },
    )
    state.awaiting_approval = True
    state.response_text = (
        f"Approval required for `{capability_name}`. "
        f"Proposal `{proposal.id}` is waiting for approval. "
        f"Review packet: action `{packet['typed_action_id']}`, params `{packet['canonical_params_json']}`. "
        f"Reply `approve {proposal.id}` to activate it."
    )
    return state


def execute_turn(*, db: Session, state: AssistantState, dependencies: GraphDependencies) -> AssistantState:
    context = _build_context(state=state, dependencies=dependencies, db=db)
    classification: TurnClassification = context.policy_context["classification"]

    if classification.request_class == "approval_decision":
        state = _handle_approval_decision(
            db=db,
            state=state,
            dependencies=dependencies,
            classification=classification,
        )
    elif classification.request_class == "revocation":
        state = _handle_revocation(
            db=db,
            state=state,
            dependencies=dependencies,
            classification=classification,
        )
    elif (
        classification.request_class == "execute_action"
        and classification.capability_name is not None
        and not dependencies.policy_service.is_tool_allowed(
            context=context,
            capability_name=classification.capability_name,
        )
    ):
        state = _handle_awaiting_approval(
            db=db,
            state=state,
            dependencies=dependencies,
            classification=classification,
        )
    else:
        bound_tools = dependencies.tool_registry.bind_tools(
            context=context,
            policy_service=dependencies.policy_service,
        )
        model_result = dependencies.model.complete_turn(
            state=state,
            available_tools=sorted(bound_tools.keys()),
        )
        state.needs_tools = model_result.needs_tools

        for request in model_result.tool_requests:
            dependencies.repository.append_tool_proposal(db, session_id=state.session_id, request=request)
            tool = bound_tools.get(request.capability_name)
            if tool is None:
                event = ToolEvent(
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    status="failed",
                    arguments=request.arguments,
                    error="tool not available in runtime context",
                )
                state.tool_events.append(event)
                dependencies.repository.append_tool_event(db, session_id=state.session_id, event=event)
                _record_governance_audit(
                    db=db,
                    dependencies=dependencies,
                    session_id=state.session_id,
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    event_kind="result",
                    status="failed",
                    payload={"arguments": request.arguments, "error": event.error},
                )
                continue

            _record_governance_audit(
                db=db,
                dependencies=dependencies,
                session_id=state.session_id,
                correlation_id=request.correlation_id,
                capability_name=request.capability_name,
                event_kind="attempt",
                status="started",
                payload={"arguments": request.arguments},
            )
            try:
                approval: ApprovalMatch | None = dependencies.policy_service.assert_execution_allowed(
                    context=context,
                    capability_name=request.capability_name,
                    arguments=request.arguments,
                )
                result = tool.invoke(request.arguments)
                outcome: dict[str, Any] = {
                    "content": result.content,
                    "metadata": result.metadata,
                }
                if approval is not None:
                    outcome["approval"] = {
                        "proposal_id": approval.proposal_id,
                        "resource_version_id": approval.resource_version_id,
                        "content_hash": approval.content_hash,
                        "typed_action_id": approval.typed_action_id,
                        "canonical_params_hash": approval.canonical_params_hash,
                        "approval_id": approval.approval_id,
                        "active_resource_id": approval.active_resource_id,
                    }
                event = ToolEvent(
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    status="succeeded",
                    arguments=request.arguments,
                    outcome=outcome,
                )
                if result.outbound_intent is not None:
                    dependencies.repository.append_outbound_intent(
                        db,
                        session_id=state.session_id,
                        correlation_id=request.correlation_id,
                        payload={
                            "text": result.outbound_intent.text,
                            "channel_kind": result.outbound_intent.channel_kind,
                            "sender_id": result.outbound_intent.sender_id,
                        },
                    )
                    event = ToolEvent(
                        correlation_id=request.correlation_id,
                        capability_name=request.capability_name,
                        status="succeeded",
                        arguments=request.arguments,
                        outcome={
                            **outcome,
                            "outbound_intent": {
                                "text": result.outbound_intent.text,
                                "channel_kind": result.outbound_intent.channel_kind,
                                "sender_id": result.outbound_intent.sender_id,
                            },
                        },
                    )
            except Exception as exc:
                event = ToolEvent(
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    status="failed",
                    arguments=request.arguments,
                    error=str(exc),
                )

            state.tool_events.append(event)
            dependencies.repository.append_tool_event(db, session_id=state.session_id, event=event)
            _record_governance_audit(
                db=db,
                dependencies=dependencies,
                session_id=state.session_id,
                correlation_id=request.correlation_id,
                capability_name=request.capability_name,
                event_kind="result",
                status=event.status,
                payload={
                    "arguments": request.arguments,
                    "outcome": event.outcome,
                    "error": event.error,
                },
            )

        if model_result.needs_tools:
            if any(event.status == "succeeded" for event in state.tool_events):
                state.response_text = "\n".join(
                    event.outcome["content"]
                    for event in state.tool_events
                    if event.outcome is not None and "content" in event.outcome
                )
            else:
                state.response_text = "I could not complete that tool request."
        else:
            state.response_text = model_result.response_text

    dependencies.repository.append_message(
        db,
        dependencies.repository.get_session(db, state.session_id),
        role="assistant",
        content=state.response_text,
        external_message_id=None,
        sender_id=state.agent_id,
        last_activity_at=datetime.now(timezone.utc),
    )
    return state
