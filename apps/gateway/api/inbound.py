from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status

from apps.gateway.deps import get_quota_service, get_session_manager, get_session_service, get_settings
from src.policies.quota import QuotaService
from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.domain.schemas import InboundMessageRequest, InboundMessageResponse
from src.gateway.idempotency import IdempotencyConflictError
from src.observability.logging import build_event, emit_event
from src.routing.service import RoutingValidationError
from src.sessions.service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbound", tags=["inbound"])


@router.post("/message", response_model=InboundMessageResponse, status_code=status.HTTP_202_ACCEPTED)
def post_inbound_message(
    payload: InboundMessageRequest,
    response: Response,
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
    service: SessionService = Depends(get_session_service),
    settings: Settings = Depends(get_settings),
    quota_service: QuotaService = Depends(get_quota_service),
) -> InboundMessageResponse:
    if settings.rate_limits_enabled:
        with session_manager.session() as db:
            decision = quota_service.check_and_increment(
                db,
                scope_kind="channel_account",
                scope_key=f"{payload.channel_kind}:{payload.channel_account_id}",
                limit=settings.inbound_requests_per_minute_per_channel_account,
                window_seconds=60,
            )
            if not decision.allowed:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate limit exceeded",
                    headers={"Retry-After": str(decision.retry_after_seconds or 60)},
                )
            db.commit()
    try:
        with session_manager.session() as db:
            try:
                result = service.process_inbound(
                    db=db,
                    channel_kind=payload.channel_kind,
                    channel_account_id=payload.channel_account_id,
                    external_message_id=payload.external_message_id,
                    sender_id=payload.sender_id,
                    content=payload.content,
                    peer_id=payload.peer_id,
                    group_id=payload.group_id,
                    attachments=[attachment.model_dump() for attachment in payload.attachments],
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
    except RoutingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    emit_event(
        logger,
        event=build_event(
            settings=settings,
            event_name="gateway.inbound.accepted",
            component="gateway",
            status=result.dedupe_status,
            trace_id=result.trace_id,
            session_id=result.session_id,
            execution_run_id=result.run_id,
            message_id=result.message_id,
            channel_kind=payload.channel_kind.strip(),
            channel_account_id=payload.channel_account_id.strip(),
            content=payload.content,
            external_message_id=payload.external_message_id.strip(),
        ),
    )
    response.headers["X-RateLimit-Scope"] = f"{payload.channel_kind}:{payload.channel_account_id}"
    return InboundMessageResponse(
        session_id=result.session_id,
        message_id=result.message_id,
        run_id=result.run_id,
        status=result.status,
        dedupe_status=result.dedupe_status,  # type: ignore[arg-type]
        trace_id=result.trace_id,
    )
