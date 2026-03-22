from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService
from src.providers.models import RuleBasedModelAdapter
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService
from src.tools.local_safe import create_echo_text_tool
from src.tools.messaging import create_send_message_tool
from src.tools.registry import ToolRegistry


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
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is not None:
        return service

    repository = SessionRepository()
    graph = GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=PolicyService(),
            model=RuleBasedModelAdapter(),
            tool_registry=ToolRegistry(
                factories={
                    "echo_text": create_echo_text_tool,
                    "send_message": create_send_message_tool,
                }
            ),
            audit_sink=ToolAuditSink(),
            transcript_context_limit=settings.runtime_transcript_context_limit,
        )
    ).build()
    return SessionService(
        repository=repository,
        assistant_graph=graph,
        idempotency_service=IdempotencyService(),
        default_agent_id=settings.default_agent_id,
        dedupe_retention_days=settings.dedupe_retention_days,
        dedupe_stale_after_seconds=settings.dedupe_stale_after_seconds,
        page_default_limit=settings.messages_page_default_limit,
        page_max_limit=settings.messages_page_max_limit,
    )
