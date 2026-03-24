from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.capabilities.repository import CapabilitiesRepository
from src.channels.dispatch_registry import build_dispatcher
from src.capabilities.activation import ActivationController
from src.context.service import ContextService
from src.db.session import DatabaseSessionManager
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService, SchedulerService
from src.observability.audit import ToolAuditSink
from src.observability.diagnostics import DiagnosticsService
from src.observability.health import HealthService
from src.policies.service import PolicyService
from src.providers.models import RuleBasedModelAdapter
from src.media.processor import MediaProcessor
from src.execution.audit import ExecutionAuditRepository
from src.execution.contracts import NodeExecutionResult
from src.execution.runtime import RemoteExecutionRuntime
from src.sandbox.service import SandboxService
from src.security.signing import SigningService
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService
from src.tools.local_safe import create_echo_text_tool
from src.tools.messaging import create_send_message_tool
from src.tools.remote_exec import create_remote_exec_tool
from src.tools.registry import ToolRegistry
from apps.node_runner.executor import NodeRunnerExecutor
from apps.node_runner.policy import NodeRunnerPolicy


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
    capability_repository = CapabilitiesRepository()
    signing_service = SigningService({settings.node_runner_signing_key_id: settings.node_runner_signing_secret})
    audit_repository = ExecutionAuditRepository()
    sandbox_service = SandboxService(settings=settings, capabilities_repository=capability_repository)
    runner_policy = NodeRunnerPolicy(
        settings=settings,
        signing_service=signing_service,
        capabilities_repository=capability_repository,
        sandbox_service=sandbox_service,
        audit_repository=audit_repository,
    )
    runner_executor = NodeRunnerExecutor(audit_repository=audit_repository)

    def runner_client(db: Session, signed_request):
        decision = runner_policy.authorize(db, signed_request=signed_request)
        if decision.should_execute:
            return runner_executor.execute(db, record=decision.record, request=signed_request.request)
        record = runner_executor.audit_repository.get_by_request_id(db, request_id=signed_request.request.request_id)
        if record is None:
            raise RuntimeError("node audit record missing after policy decision")
        return NodeExecutionResult(
            request_id=record.request_id,
            status=record.status,
            exit_code=record.exit_code,
            stdout_preview=record.stdout_preview,
            stderr_preview=record.stderr_preview,
            stdout_truncated=record.stdout_truncated,
            stderr_truncated=record.stderr_truncated,
            deny_reason=record.deny_reason,
        )

    remote_runtime = RemoteExecutionRuntime(
        settings=settings,
        capabilities_repository=capability_repository,
        sandbox_service=sandbox_service,
        signing_service=signing_service,
        runner_client=runner_client,
    )
    policy_service = PolicyService(remote_execution_enabled=settings.remote_execution_enabled)
    return GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=policy_service,
            model=RuleBasedModelAdapter(),
            tool_registry=ToolRegistry(
                factories={
                    "echo_text": create_echo_text_tool,
                    "send_message": create_send_message_tool,
                    "remote_exec": create_remote_exec_tool,
                }
            ),
            audit_sink=ToolAuditSink(),
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(
                context_window=settings.runtime_transcript_context_limit,
                settings=settings,
            ),
            remote_execution_runtime=remote_runtime,
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
    dispatcher = build_dispatcher()
    dispatcher.settings = settings
    return RunExecutionService(
        settings=settings,
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
        media_processor=MediaProcessor(
            storage_root=(Path(settings.media_storage_root)),
            storage_bucket=settings.media_storage_bucket,
            retention_days=settings.media_retention_days,
            max_bytes=settings.media_max_bytes,
            allowed_schemes=tuple(item.strip() for item in settings.media_allowed_schemes.split(",") if item.strip()),
            allowed_mime_prefixes=tuple(
                item.strip() for item in settings.media_allowed_mime_prefixes.split(",") if item.strip()
            ),
        ),
        outbound_dispatcher=dispatcher,
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


def get_health_service(
    settings: Settings = Depends(get_settings),
) -> HealthService:
    return HealthService(settings=settings)


def get_diagnostics_service(
    settings: Settings = Depends(get_settings),
) -> DiagnosticsService:
    return DiagnosticsService(settings=settings)


def verify_operator_access(
    *,
    settings: Settings,
    authorization: str | None,
    x_internal_service_token: str | None,
) -> None:
    admin_token = settings.diagnostics_admin_bearer_token
    internal_token = settings.diagnostics_internal_service_token
    admin_ok = bool(admin_token and authorization == f"Bearer {admin_token}")
    internal_ok = bool(internal_token and x_internal_service_token == internal_token)
    if admin_ok or internal_ok:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="operator authorization required")


def require_operator_access(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
    x_internal_service_token: str | None = Header(default=None),
) -> None:
    verify_operator_access(
        settings=settings,
        authorization=authorization,
        x_internal_service_token=x_internal_service_token,
    )
