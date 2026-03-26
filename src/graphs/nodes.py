from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.context.service import ContextService
from src.graphs.prompts import build_prompt_payload
from src.graphs.state import (
    AssistantState,
    RejectedToolRequest,
    ToolEvent,
    ToolRequest,
    ToolRuntimeContext,
    ToolRuntimeServices,
    ValidatedToolCall,
)
from src.observability.audit import ToolAuditEvent
from src.policies.service import ApprovalMatch, TurnClassification, canonicalize_tool_arguments
from src.tools.registry import ToolRegistry, ToolSchemaValidationError
from src.tools.typed_actions import get_typed_action


@dataclass
class GraphDependencies:
    repository: Any
    policy_service: Any
    model: Any
    tool_registry: ToolRegistry
    audit_sink: Any
    activation_controller: Any
    context_service: ContextService
    remote_execution_runtime: Any | None = None


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
    return dependencies.context_service.assemble(
        db=db,
        repository=dependencies.repository,
        session_id=session_id,
        message_id=message_id,
        agent_id=agent_id,
        channel_kind=channel_kind,
        sender_id=sender_id,
        user_text=user_text,
    )


def _build_context(*, state: AssistantState, dependencies: GraphDependencies, db: Session) -> ToolRuntimeContext:
    policy_context = dependencies.policy_service.build_policy_context(
        db,
        repository=dependencies.repository,
        session_id=state.session_id,
        agent_id=state.agent_id,
        user_text=state.user_text,
    )
    existing_services = dependencies.model.runtime_services()
    return ToolRuntimeContext(
        session_id=state.session_id,
        message_id=state.message_id,
        agent_id=state.agent_id,
        channel_kind=state.channel_kind,
        sender_id=state.sender_id,
        policy_context=policy_context,
        runtime_services=ToolRuntimeServices(
            clock=getattr(existing_services, "clock", None),
            db=db,
            execution_run_id=state.context_manifest.get("execution_run_id"),
            remote_execution_runtime=dependencies.remote_execution_runtime,
            policy_service=dependencies.policy_service,
        ),
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
        tool_schema_name=f"{capability_name}.input",
        tool_schema_version="1.0",
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
            "tool_schema_name": packet["tool_schema_name"],
            "tool_schema_version": packet["tool_schema_version"],
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


def _persist_provider_metadata(*, state: AssistantState, model_result: Any) -> None:
    if not model_result.execution_metadata:
        return
    state.context_manifest["model_execution"] = {
        key: model_result.execution_metadata.get(key)
        for key in (
            "provider_name",
            "model_name",
            "prompt_strategy_id",
            "tool_call_mode",
            "provider_attempt_count",
            "semantic_fallback_kind",
        )
    }


def _request_requires_approval(*, capability_name: str) -> bool:
    typed_action = get_typed_action(capability_name)
    return bool(typed_action and typed_action.requires_approval)


def _build_tool_metadata(*, call: ValidatedToolCall) -> dict[str, Any]:
    return {
        "tool_schema_name": call.tool_schema_name,
        "tool_schema_version": call.schema_version,
        "typed_action_id": call.typed_action_id,
        "canonical_arguments_json": call.canonical_arguments_json,
        "canonical_arguments": call.canonical_arguments,
        **call.metadata,
    }


def _validation_guidance(*, capability_name: str, error: ToolSchemaValidationError) -> str:
    if not error.issues:
        return f"Invalid arguments for `{capability_name}`."
    issue_text = "; ".join(f"{issue.field_path}: {issue.message}" for issue in error.issues[:3])
    return f"Invalid arguments for `{capability_name}`. {issue_text}"


def _validate_tool_request(
    *,
    request: ToolRequest,
    bound_tools: dict[str, Any],
) -> ValidatedToolCall:
    tool = bound_tools.get(request.capability_name)
    if tool is None:
        raise LookupError("tool not available in runtime context")
    validated_request, canonical_arguments, canonical_arguments_json = canonicalize_tool_arguments(
        tool=tool,
        arguments=request.arguments,
    )
    return ValidatedToolCall(
        correlation_id=request.correlation_id,
        capability_name=request.capability_name,
        tool_schema_name=tool.tool_schema_name,
        schema_version=tool.schema_version,
        typed_action_id=tool.typed_action_id,
        requires_approval=tool.requires_approval,
        raw_arguments=request.arguments,
        validated_request=validated_request,
        canonical_arguments=canonical_arguments,
        canonical_arguments_json=canonical_arguments_json,
        metadata=request.metadata,
    )


def _handle_governed_tool_request(
    *,
    db: Session,
    state: AssistantState,
    dependencies: GraphDependencies,
    call: ValidatedToolCall,
) -> ToolEvent:
    proposal, version = dependencies.repository.create_governance_proposal(
        db,
        session_id=state.session_id,
        message_id=state.message_id,
        agent_id=state.agent_id,
        requested_by=state.sender_id,
        capability_name=call.capability_name,
        arguments=call.canonical_arguments,
        tool_schema_name=call.tool_schema_name,
        tool_schema_version=call.schema_version,
    )
    packet = dependencies.repository.get_proposal_packet(db, proposal_id=proposal.id)
    _record_governance_audit(
        db=db,
        dependencies=dependencies,
        session_id=state.session_id,
        correlation_id=proposal.id,
        capability_name=call.capability_name,
        event_kind="approval_requested",
        status="pending_approval",
        payload={
            "proposal_id": proposal.id,
            "resource_version_id": version.id,
            "content_hash": version.content_hash,
            "typed_action_id": packet["typed_action_id"],
            "tool_schema_name": packet["tool_schema_name"],
            "tool_schema_version": packet["tool_schema_version"],
            "canonical_params_hash": packet["canonical_params_hash"],
            "llm_originated": True,
        },
    )
    state.awaiting_approval = True
    state.response_text = (
        f"Approval required for `{call.capability_name}`. "
        f"Proposal `{proposal.id}` is waiting for approval. "
        f"Reply `approve {proposal.id}` to activate it."
    )
    return ToolEvent(
        correlation_id=proposal.id,
        capability_name=call.capability_name,
        status="awaiting_approval",
        arguments=call.canonical_arguments,
        outcome={"proposal_id": proposal.id},
        metadata=_build_tool_metadata(call=call),
    )


def _record_rejected_tool_request(
    *,
    db: Session,
    state: AssistantState,
    dependencies: GraphDependencies,
    rejected: RejectedToolRequest,
) -> ToolEvent:
    capability_name = rejected.capability_name or "unknown"
    event = ToolEvent(
        correlation_id=rejected.correlation_id,
        capability_name=capability_name,
        status="failed",
        arguments=rejected.arguments,
        error=rejected.error,
        metadata=rejected.metadata,
    )
    if rejected.capability_name is not None:
        dependencies.repository.append_tool_event(db, session_id=state.session_id, event=event)
    _record_governance_audit(
        db=db,
        dependencies=dependencies,
        session_id=state.session_id,
        correlation_id=rejected.correlation_id,
        capability_name=capability_name,
        event_kind="result",
        status="failed",
        payload={"arguments": rejected.arguments, "error": rejected.error, "semantic": True},
    )
    return event


def execute_turn(*, db: Session, state: AssistantState, dependencies: GraphDependencies) -> AssistantState:
    if state.degraded:
        state.response_text = (
            "I could not safely fit the required session context into the model window for this turn. "
            "Continuity repair has been queued."
        )
        dependencies.repository.append_message(
            db,
            dependencies.repository.get_session(db, state.session_id),
            role="assistant",
            content=state.response_text,
            external_message_id=None,
            sender_id=state.agent_id,
            last_activity_at=datetime.now(timezone.utc),
        )
        dependencies.context_service.persist_manifest(db=db, repository=dependencies.repository, state=state)
        return state

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
    else:
        bound_tools = dependencies.tool_registry.bind_tools(context=context, policy_service=dependencies.policy_service)
        state.bound_tools = bound_tools
        state.llm_prompt = build_prompt_payload(
            state=state,
            visible_tools=list(bound_tools.values()),
            tool_call_mode="none" if getattr(dependencies, "settings", None) and dependencies.settings.llm_disable_tools else "auto",
        )
        raw_requests: list[ToolRequest] = []
        if classification.request_class == "execute_action" and classification.capability_name is not None:
            raw_requests.append(
                ToolRequest(
                    correlation_id=f"policy:{state.message_id}:{classification.capability_name}",
                    capability_name=classification.capability_name,
                    arguments=classification.arguments or {},
                    metadata={"source": "policy"},
                )
            )
            model_result = None
            state.needs_tools = True
        else:
            model_result = dependencies.model.complete_turn(
                state=state,
                available_tools=sorted(bound_tools.keys()),
            )
            raw_requests.extend(model_result.tool_requests)
            state.needs_tools = model_result.needs_tools
            _persist_provider_metadata(state=state, model_result=model_result)

            for rejected in model_result.rejected_tool_requests:
                state.tool_events.append(
                    _record_rejected_tool_request(
                        db=db,
                        state=state,
                        dependencies=dependencies,
                        rejected=rejected,
                    )
                )

        for request in raw_requests:
            try:
                call = _validate_tool_request(request=request, bound_tools=bound_tools)
            except LookupError:
                dependencies.repository.append_tool_proposal(db, session_id=state.session_id, request=request)
                event = ToolEvent(
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    status="failed",
                    arguments=request.arguments,
                    error="tool not available in runtime context",
                    metadata=request.metadata,
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
            except ToolSchemaValidationError as exc:
                dependencies.repository.append_tool_proposal(db, session_id=state.session_id, request=request)
                guidance = _validation_guidance(capability_name=request.capability_name, error=exc)
                event = ToolEvent(
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    status="failed",
                    arguments=request.arguments,
                    error=guidance,
                    metadata={
                        **request.metadata,
                        "validation_error_code": exc.code,
                        "validation_error_fields": [issue.field_path for issue in exc.issues],
                    },
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
                    payload={
                        "arguments": request.arguments,
                        "error": guidance,
                        "validation_error_code": exc.code,
                        "validation_error_fields": [issue.field_path for issue in exc.issues],
                    },
                )
                if not state.response_text:
                    state.response_text = guidance
                continue

            if call.requires_approval and not dependencies.policy_service.has_exact_approval(context=context, call=call):
                state.tool_events.append(
                    _handle_governed_tool_request(
                        db=db,
                        state=state,
                        dependencies=dependencies,
                        call=call,
                    )
                )
                continue

            dependencies.repository.append_tool_proposal(
                db,
                session_id=state.session_id,
                request=ToolRequest(
                    correlation_id=call.correlation_id,
                    capability_name=call.capability_name,
                    arguments=call.canonical_arguments,
                    metadata=_build_tool_metadata(call=call),
                ),
            )

            tool = bound_tools[call.capability_name]

            _record_governance_audit(
                db=db,
                dependencies=dependencies,
                session_id=state.session_id,
                correlation_id=call.correlation_id,
                capability_name=call.capability_name,
                event_kind="attempt",
                status="started",
                payload={
                    "arguments": call.canonical_arguments,
                    "tool_schema_name": call.tool_schema_name,
                    "tool_schema_version": call.schema_version,
                    "canonical_arguments_json": call.canonical_arguments_json,
                },
            )
            try:
                approval: ApprovalMatch | None = dependencies.policy_service.assert_execution_allowed(
                    context=context,
                    call=call,
                )
                context.policy_context["validated_call"] = call
                result = tool.invoke(call.validated_request)
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
                        "tool_schema_name": approval.tool_schema_name,
                        "tool_schema_version": approval.tool_schema_version,
                        "canonical_params_hash": approval.canonical_params_hash,
                        "approval_id": approval.approval_id,
                        "active_resource_id": approval.active_resource_id,
                    }
                event = ToolEvent(
                    correlation_id=call.correlation_id,
                    capability_name=call.capability_name,
                    status="succeeded",
                    arguments=call.canonical_arguments,
                    outcome=outcome,
                    metadata=_build_tool_metadata(call=call),
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
                            "media_refs": result.outbound_intent.media_refs,
                            "reply_to_external_id": result.outbound_intent.reply_to_external_id,
                            "execution_run_id": context.runtime_services.execution_run_id,
                        },
                    )
                    event = ToolEvent(
                        correlation_id=call.correlation_id,
                        capability_name=call.capability_name,
                        status="succeeded",
                        arguments=call.canonical_arguments,
                        outcome={
                            **outcome,
                            "outbound_intent": {
                                "text": result.outbound_intent.text,
                                "channel_kind": result.outbound_intent.channel_kind,
                                "sender_id": result.outbound_intent.sender_id,
                                "media_refs": result.outbound_intent.media_refs,
                                "reply_to_external_id": result.outbound_intent.reply_to_external_id,
                            },
                        },
                        metadata=_build_tool_metadata(call=call),
                    )
            except Exception as exc:
                event = ToolEvent(
                    correlation_id=call.correlation_id,
                    capability_name=call.capability_name,
                    status="failed",
                    arguments=call.canonical_arguments,
                    error=str(exc),
                    metadata=_build_tool_metadata(call=call),
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
                    "arguments": event.arguments,
                    "tool_schema_name": event.metadata.get("tool_schema_name"),
                    "tool_schema_version": event.metadata.get("tool_schema_version"),
                    "canonical_arguments_json": event.metadata.get("canonical_arguments_json"),
                    "outcome": event.outcome,
                    "error": event.error,
                },
            )

        if state.needs_tools:
            if state.awaiting_approval:
                pass
            elif any(event.status == "succeeded" for event in state.tool_events):
                state.response_text = "\n".join(
                    event.outcome["content"]
                    for event in state.tool_events
                    if event.outcome is not None and "content" in event.outcome
                )
            elif not state.response_text:
                state.response_text = "I could not complete that tool request."
        elif model_result is not None and not state.response_text:
            state.response_text = model_result.response_text

    assistant_message = dependencies.repository.append_message(
        db,
        dependencies.repository.get_session(db, state.session_id),
        role="assistant",
        content=state.response_text,
        external_message_id=None,
        sender_id=state.agent_id,
        last_activity_at=datetime.now(timezone.utc),
    )
    state.assistant_message_id = assistant_message.id
    dependencies.context_service.persist_manifest(db=db, repository=dependencies.repository, state=state)
    return state
