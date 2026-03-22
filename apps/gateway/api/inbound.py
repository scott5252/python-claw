from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from apps.gateway.deps import get_session_manager, get_session_service
from src.db.session import DatabaseSessionManager
from src.domain.schemas import InboundMessageRequest, InboundMessageResponse
from src.gateway.idempotency import IdempotencyConflictError
from src.routing.service import RoutingValidationError
from src.sessions.service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbound", tags=["inbound"])


@router.post("/message", response_model=InboundMessageResponse, status_code=status.HTTP_201_CREATED)
def post_inbound_message(
    payload: InboundMessageRequest,
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
    service: SessionService = Depends(get_session_service),
) -> InboundMessageResponse:
    try:
        with session_manager.session() as claim_db:
            with session_manager.session() as work_db:
                result = service.process_inbound(
                    claim_db=claim_db,
                    work_db=work_db,
                    channel_kind=payload.channel_kind,
                    channel_account_id=payload.channel_account_id,
                    external_message_id=payload.external_message_id,
                    sender_id=payload.sender_id,
                    content=payload.content,
                    peer_id=payload.peer_id,
                    group_id=payload.group_id,
                )
    except RoutingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    log_payload = {
        "channel_kind": payload.channel_kind.strip(),
        "channel_account_id": payload.channel_account_id.strip(),
        "external_message_id": payload.external_message_id.strip(),
        "session_id": result.session_id,
        "status": result.dedupe_status,
    }
    logger.info("inbound message processed", extra=log_payload)
    return InboundMessageResponse(
        session_id=result.session_id,
        message_id=result.message_id,
        dedupe_status=result.dedupe_status,  # type: ignore[arg-type]
    )
