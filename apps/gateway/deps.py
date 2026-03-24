from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.capabilities.activation import ActivationController
from src.context.service import ContextService
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService, SchedulerService
from src.observability.audit import ToolAuditSink
from src.policies.service import PolicyService
from src.providers.models import RuleBasedModelAdapter
from src.sessions.concurrency import SessionConcurrencyService
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


def build_assistant_graph(settings: Settings, repository: SessionRepository):
    return GraphFactory(
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
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(context_window=settings.runtime_transcript_context_limit),
        )
    ).build()


def create_session_service(settings: Settings) -> SessionService:
    repository = SessionRepository()
    return SessionService(
        repository=repository,
        jobs_repository=JobsRepository(),
        idempotency_service=IdempotencyService(),
        default_agent_id=settings.default_agent_id,
        dedupe_retention_days=settings.dedupe_retention_days,
        dedupe_stale_after_seconds=settings.dedupe_stale_after_seconds,
        messages_page_default_limit=settings.messages_page_default_limit,
        messages_page_max_limit=settings.messages_page_max_limit,
        session_runs_page_default_limit=settings.session_runs_page_default_limit,
        session_runs_page_max_limit=settings.session_runs_page_max_limit,
        execution_run_max_attempts=settings.execution_run_max_attempts,
    )


def create_run_execution_service(settings: Settings) -> RunExecutionService:
    repository = SessionRepository()
    jobs_repository = JobsRepository()
    return RunExecutionService(
        jobs_repository=jobs_repository,
        session_repository=repository,
        concurrency_service=SessionConcurrencyService(
            repository=jobs_repository,
            lease_seconds=settings.execution_run_lease_seconds,
            global_concurrency_limit=settings.execution_run_global_concurrency,
        ),
        assistant_graph_factory=lambda: build_assistant_graph(settings, repository),
        failure_classifier=FailureClassifier(),
        base_backoff_seconds=settings.execution_run_backoff_seconds,
        max_backoff_seconds=settings.execution_run_backoff_max_seconds,
    )


def create_scheduler_service(settings: Settings) -> SchedulerService:
    repository = SessionRepository()
    jobs_repository = JobsRepository()
    session_service = create_session_service(settings)
    return SchedulerService(
        jobs_repository=jobs_repository,
        session_repository=repository,
        submit_scheduler_run=session_service.submit_scheduler_fire,
    )


def get_session_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is not None:
        return service
    return create_session_service(settings)


def get_run_execution_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RunExecutionService:
    service = getattr(request.app.state, "run_execution_service", None)
    if service is not None:
        return service
    return create_run_execution_service(settings)


def get_scheduler_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SchedulerService:
    service = getattr(request.app.state, "scheduler_service", None)
    if service is not None:
        return service
    return create_scheduler_service(settings)
