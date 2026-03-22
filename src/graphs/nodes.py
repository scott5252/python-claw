from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.graphs.prompts import render_prompt
from src.graphs.state import AssistantState, ToolEvent, ToolRuntimeContext
from src.observability.audit import ToolAuditEvent
from src.tools.registry import ToolRegistry


@dataclass
class GraphDependencies:
    repository: any
    policy_service: any
    model: any
    tool_registry: ToolRegistry
    audit_sink: any
    transcript_context_limit: int


def assemble_state(
    *,
    db: Session,
    dependencies: GraphDependencies,
    session_id: str,
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
        agent_id=agent_id,
        channel_kind=channel_kind,
        sender_id=sender_id,
        user_text=user_text,
        messages=messages,
    )


def execute_turn(*, db: Session, state: AssistantState, dependencies: GraphDependencies) -> AssistantState:
    context = ToolRuntimeContext(
        session_id=state.session_id,
        agent_id=state.agent_id,
        channel_kind=state.channel_kind,
        sender_id=state.sender_id,
        policy_context={"prompt": render_prompt(state)},
        runtime_services=dependencies.model.runtime_services(),
    )
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
            dependencies.audit_sink.record(
                db,
                ToolAuditEvent(
                    session_id=state.session_id,
                    correlation_id=request.correlation_id,
                    capability_name=request.capability_name,
                    event_kind="result",
                    status="failed",
                    payload={"arguments": request.arguments, "error": event.error},
                ),
            )
            continue

        dependencies.audit_sink.record(
            db,
            ToolAuditEvent(
                session_id=state.session_id,
                correlation_id=request.correlation_id,
                capability_name=request.capability_name,
                event_kind="attempt",
                status="started",
                payload={"arguments": request.arguments},
            ),
        )
        try:
            result = tool.invoke(request.arguments)
            event = ToolEvent(
                correlation_id=request.correlation_id,
                capability_name=request.capability_name,
                status="succeeded",
                arguments=request.arguments,
                outcome={
                    "content": result.content,
                    "metadata": result.metadata,
                },
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
                        "content": result.content,
                        "metadata": result.metadata,
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
        dependencies.audit_sink.record(
            db,
            ToolAuditEvent(
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
            ),
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
