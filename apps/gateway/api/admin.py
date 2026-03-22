from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from apps.gateway.deps import get_db, get_session_service
from src.domain.schemas import MessagePageResponse, SessionResponse
from src.sessions.service import SessionService

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> SessionResponse:
    session = service.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=MessagePageResponse)
def get_session_messages(
    session_id: str,
    limit: int | None = Query(default=None, ge=1),
    before_message_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    service: SessionService = Depends(get_session_service),
) -> MessagePageResponse:
    page = service.get_messages(
        db,
        session_id=session_id,
        limit=limit,
        before_message_id=before_message_id,
    )
    if page is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return page
