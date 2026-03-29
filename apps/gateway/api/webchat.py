from __future__ import annotations

from uuid import uuid4
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from apps.gateway.deps import get_approval_decision_service, get_db, get_session_manager, get_session_service, get_settings
from src.policies.approval_actions import ApprovalDecisionService
from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.domain.schemas import (
    WebchatDeliveryPollItem,
    WebchatDeliveryPollResponse,
    WebchatInboundRequest,
    WebchatInboundResponse,
    WebchatStreamEventPayload,
    ApprovalActionPromptResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
)
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService

router = APIRouter(prefix="/providers/webchat", tags=["providers"])


def _verify_webchat_access(*, account, token: str | None) -> None:
    expected = account.webchat_client_token if account.mode == "real" else "fake-webchat-token"
    if not expected or token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webchat client token")


@router.post("/accounts/{channel_account_id}/messages", response_model=WebchatInboundResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_webchat_message(
    channel_account_id: str,
    payload: WebchatInboundRequest,
    x_webchat_client_token: str | None = Header(default=None),
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
    service: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
) -> WebchatInboundResponse:
    account = settings.get_channel_account(channel_kind="webchat", channel_account_id=channel_account_id)
    _verify_webchat_access(account=account, token=x_webchat_client_token)
    external_message_id = payload.message_id or f"webchat:{uuid4()}"
    stream_id = payload.stream_id or payload.group_id or payload.peer_id or payload.actor_id
    with session_manager.session() as db:
        result = service.process_inbound(
            db=db,
            channel_kind="webchat",
            channel_account_id=channel_account_id,
            external_message_id=external_message_id,
            sender_id=payload.actor_id,
            content=payload.content,
            peer_id=payload.peer_id or (None if payload.group_id else payload.actor_id),
            group_id=payload.group_id,
            attachments=[attachment.model_dump() for attachment in payload.attachments],
            transport_address_key=stream_id,
            transport_address={"provider": "webchat", "address_key": stream_id, "metadata": {"stream_id": stream_id}},
        )
        db.commit()
    return WebchatInboundResponse(
        session_id=result.session_id,
        message_id=result.message_id,
        run_id=result.run_id,
        status=result.status,
        dedupe_status=result.dedupe_status,  # type: ignore[arg-type]
        trace_id=result.trace_id,
        external_message_id=external_message_id,
    )


@router.get("/accounts/{channel_account_id}/poll", response_model=WebchatDeliveryPollResponse)
def poll_webchat_deliveries(
    channel_account_id: str,
    stream_id: str = Query(...),
    after_delivery_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    x_webchat_client_token: str | None = Header(default=None),
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WebchatDeliveryPollResponse:
    account = settings.get_channel_account(channel_kind="webchat", channel_account_id=channel_account_id)
    _verify_webchat_access(account=account, token=x_webchat_client_token)
    repository = SessionRepository()
    rows = repository.list_webchat_deliveries(
        db,
        channel_account_id=channel_account_id,
        stream_id=stream_id,
        after_delivery_id=after_delivery_id,
        limit=limit,
    )
    items = [
        WebchatDeliveryPollItem(
            delivery_id=row.id,
            status=row.status,
            delivery_kind=row.delivery_kind,
            provider_message_id=row.provider_message_id,
            created_at=row.created_at,
            payload=json.loads(row.delivery_payload_json or "{}"),
            provider_metadata=json.loads(row.provider_metadata_json or "{}"),
        )
        for row in rows
    ]
    next_after = items[-1].delivery_id if items else after_delivery_id
    return WebchatDeliveryPollResponse(items=items, next_after_delivery_id=next_after)


@router.get("/accounts/{channel_account_id}/stream")
def stream_webchat_deliveries(
    channel_account_id: str,
    stream_id: str = Query(...),
    after_event_id: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    x_webchat_client_token: str | None = Header(default=None),
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    account = settings.get_channel_account(channel_kind="webchat", channel_account_id=channel_account_id)
    _verify_webchat_access(account=account, token=x_webchat_client_token)
    repository = SessionRepository()
    resolved_after = after_event_id
    if resolved_after is None and last_event_id:
        try:
            resolved_after = int(last_event_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Last-Event-ID") from exc
    rows = repository.list_webchat_stream_events(
        db,
        channel_account_id=channel_account_id,
        stream_id=stream_id,
        after_event_id=resolved_after,
        limit=limit,
    )

    def event_iter():
        for row in rows:
            payload = WebchatStreamEventPayload(
                event_id=row.id,
                delivery_id=row.outbound_delivery_id,
                attempt_id=row.outbound_delivery_attempt_id,
                sequence_number=row.sequence_number,
                event_kind=row.event_kind,
                payload=json.loads(row.payload_json or "{}"),
                created_at=row.created_at,
            )
            yield f"id: {payload.event_id}\n"
            yield "event: delivery\n"
            yield f"data: {payload.model_dump_json()}\n\n"

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("/accounts/{channel_account_id}/approval-prompts", response_model=list[ApprovalActionPromptResponse])
def list_webchat_approval_prompts(
    channel_account_id: str,
    stream_id: str = Query(...),
    x_webchat_client_token: str | None = Header(default=None),
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ApprovalActionPromptResponse]:
    account = settings.get_channel_account(channel_kind="webchat", channel_account_id=channel_account_id)
    _verify_webchat_access(account=account, token=x_webchat_client_token)
    repository = SessionRepository()
    items = [
        ApprovalActionPromptResponse.model_validate(item, from_attributes=True)
        for item in repository.list_approval_action_prompts_for_surface(
            db,
            channel_kind="webchat",
            channel_account_id=channel_account_id,
            transport_address_key=stream_id,
        )
    ]
    return items


@router.post("/accounts/{channel_account_id}/approval-actions", response_model=ApprovalDecisionResponse)
def submit_webchat_approval_decision(
    channel_account_id: str,
    payload: ApprovalDecisionRequest,
    x_webchat_client_token: str | None = Header(default=None),
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
    approvals: ApprovalDecisionService = Depends(get_approval_decision_service),
) -> ApprovalDecisionResponse:
    account = settings.get_channel_account(channel_kind="webchat", channel_account_id=channel_account_id)
    _verify_webchat_access(account=account, token=x_webchat_client_token)
    if not payload.proposal_id and not payload.token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="proposal_id or token required")
    try:
        result = approvals.decide(
            db,
            session_id="",
            message_id=None,
            actor_id="webchat-user",
            decision=payload.decision,
            proposal_id=payload.proposal_id,
            token=payload.token,
            decided_via="channel_action",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return ApprovalDecisionResponse.model_validate(result, from_attributes=True)
