from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_manager(request: Request) -> DatabaseSessionManager:
    return request.app.state.session_manager


def get_db(
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
):
    with session_manager.session() as db:
        yield db


def get_session_service(
    settings: Settings = Depends(get_settings),
) -> SessionService:
    return SessionService(
        repository=SessionRepository(),
        idempotency_service=IdempotencyService(),
        dedupe_retention_days=settings.dedupe_retention_days,
        dedupe_stale_after_seconds=settings.dedupe_stale_after_seconds,
        page_default_limit=settings.messages_page_default_limit,
        page_max_limit=settings.messages_page_max_limit,
    )
