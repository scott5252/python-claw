from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.agents.bootstrap import bootstrap_agent_profiles
from src.agents.repository import AgentRepository
from src.agents.service import AgentExecutionBinding, AgentProfileService
from src.config.settings import Settings
from src.capabilities.repository import CapabilitiesRepository
from src.channels.dispatch_registry import build_dispatcher
from src.capabilities.activation import ActivationController
from src.context.service import ContextService
from src.db.session import DatabaseSessionManager
from src.delegations.repository import DelegationRepository
from src.delegations.service import DelegationService
from src.gateway.idempotency import IdempotencyService
from src.graphs.assistant_graph import GraphFactory
from src.graphs.nodes import GraphDependencies
from src.jobs.repository import JobsRepository
from src.jobs.service import FailureClassifier, RunExecutionService, SchedulerService
from src.observability.audit import ToolAuditSink
from src.observability.diagnostics import DiagnosticsService
from src.observability.health import HealthService
from src.policies.service import PolicyService
from src.providers.models import ProviderBackedModelAdapter, RuleBasedModelAdapter
from src.media.processor import MediaProcessor
from src.media.extraction import MediaExtractionService
from src.memory.service import MemoryService
from src.retrieval.service import RetrievalService
from src.execution.audit import ExecutionAuditRepository
from src.execution.contracts import NodeExecutionResult
from src.execution.runtime import RemoteExecutionRuntime
from src.sandbox.service import SandboxService
from src.security.signing import SigningService
from src.sessions.concurrency import SessionConcurrencyService
from src.sessions.repository import SessionRepository
from src.sessions.service import SessionService
from src.tools.local_safe import create_echo_text_tool
from src.tools.delegation import create_delegate_to_agent_tool
from src.tools.messaging import create_send_message_tool
from src.tools.remote_exec import create_remote_exec_tool
from src.tools.registry import ToolRegistry
from apps.node_runner.executor import NodeRunnerExecutor
from apps.node_runner.policy import NodeRunnerPolicy


def _build_model_adapter(settings: Settings, *, binding: AgentExecutionBinding):
    if binding.model.runtime_mode == "rule_based":
        return RuleBasedModelAdapter()
    if binding.model.runtime_mode == "provider":
        return ProviderBackedModelAdapter(settings=settings, model_profile=binding.model)
    raise ValueError(f"unsupported runtime mode: {binding.model.runtime_mode}")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_manager(request: Request) -> DatabaseSessionManager:
    return request.app.state.session_manager


def get_db(
    session_manager: DatabaseSessionManager = Depends(get_session_manager),
):
    with session_manager.session() as db:
        yield db


def create_delegation_service(settings: Settings) -> DelegationService:
    session_repository = SessionRepository()
    jobs_repository = JobsRepository()
    return DelegationService(
        repository=DelegationRepository(
            session_repository=session_repository,
            jobs_repository=jobs_repository,
        ),
        session_repository=session_repository,
        jobs_repository=jobs_repository,
        agent_profile_service=AgentProfileService(repository=AgentRepository(), settings=settings),
        settings=settings,
    )


def build_assistant_graph(
    settings: Settings,
    repository: SessionRepository,
    *,
    binding: AgentExecutionBinding,
    delegation_service: DelegationService | None = None,
):
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
    policy_service = PolicyService(
        denied_capabilities=set(binding.policy_profile.denied_capability_names),
        remote_execution_enabled=binding.policy_profile.remote_execution_enabled,
        allowed_capabilities=set(binding.tool_profile.allowed_capability_names),
        policy_profile_key=binding.policy_profile_key,
        tool_profile_key=binding.tool_profile_key,
        delegation_enabled=binding.policy_profile.delegation_enabled,
        max_delegation_depth=binding.policy_profile.max_delegation_depth,
        allowed_child_agent_ids=set(binding.policy_profile.allowed_child_agent_ids),
        max_active_delegations_per_run=binding.policy_profile.max_active_delegations_per_run,
        max_active_delegations_per_session=binding.policy_profile.max_active_delegations_per_session,
    )
    retrieval_service = RetrievalService(
        strategy_id=settings.retrieval_strategy_id,
        chunk_chars=settings.retrieval_chunk_chars,
        min_score=settings.retrieval_min_score,
    )
    return GraphFactory(
        GraphDependencies(
            repository=repository,
            policy_service=policy_service,
            model=_build_model_adapter(settings, binding=binding),
            tool_registry=ToolRegistry(
                factories={
                    "echo_text": create_echo_text_tool,
                    "send_message": create_send_message_tool,
                    "remote_exec": create_remote_exec_tool,
                    "delegate_to_agent": create_delegate_to_agent_tool,
                }
            ),
            audit_sink=ToolAuditSink(),
            activation_controller=ActivationController(repository=repository),
            context_service=ContextService(
                context_window=settings.runtime_transcript_context_limit,
                settings=settings,
                retrieval_service=retrieval_service,
            ),
            remote_execution_runtime=remote_runtime,
            delegation_service=delegation_service,
        )
    ).build()


def create_session_service(settings: Settings) -> SessionService:
    repository = SessionRepository()
    agent_profile_service = AgentProfileService(repository=AgentRepository(), settings=settings)
    return SessionService(
        repository=repository,
        jobs_repository=JobsRepository(),
        agent_profile_service=agent_profile_service,
        idempotency_service=IdempotencyService(),
        dedupe_retention_days=settings.dedupe_retention_days,
        dedupe_stale_after_seconds=settings.dedupe_stale_after_seconds,
        messages_page_default_limit=settings.messages_page_default_limit,
        messages_page_max_limit=settings.messages_page_max_limit,
        session_runs_page_default_limit=settings.session_runs_page_default_limit,
        session_runs_page_max_limit=settings.session_runs_page_max_limit,
        execution_run_max_attempts=settings.execution_run_max_attempts,
    )


def create_run_execution_service(
    settings: Settings,
    *,
    delegation_service: DelegationService | None = None,
) -> RunExecutionService:
    repository = SessionRepository()
    jobs_repository = JobsRepository()
    agent_profile_service = AgentProfileService(repository=AgentRepository(), settings=settings)
    resolved_delegation_service = delegation_service or create_delegation_service(settings)
    dispatcher = build_dispatcher(settings)
    attachment_extraction_service = MediaExtractionService(
        storage_root=Path(settings.media_storage_root),
        strategy_id=settings.attachment_extraction_strategy_id,
        same_run_max_bytes=settings.attachment_same_run_max_bytes,
        same_run_pdf_page_limit=settings.attachment_same_run_pdf_page_limit,
        same_run_timeout_seconds=settings.attachment_same_run_timeout_seconds,
    )
    return RunExecutionService(
        settings=settings,
        jobs_repository=jobs_repository,
        session_repository=repository,
        concurrency_service=SessionConcurrencyService(
            repository=jobs_repository,
            lease_seconds=settings.execution_run_lease_seconds,
            global_concurrency_limit=settings.execution_run_global_concurrency,
        ),
        agent_profile_service=agent_profile_service,
        assistant_graph_factory=lambda binding: build_assistant_graph(
            settings,
            repository,
            binding=binding,
            delegation_service=resolved_delegation_service,
        ),
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
        attachment_extraction_service=attachment_extraction_service,
        outbound_dispatcher=dispatcher,
        delegation_service=resolved_delegation_service,
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


def bootstrap_runtime_state(*, settings: Settings, session_manager: DatabaseSessionManager) -> None:
    with session_manager.session() as db:
        bootstrap_agent_profiles(db, settings=settings)
        db.commit()


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
    delegation_service = getattr(request.app.state, "delegation_service", None)
    return create_run_execution_service(settings, delegation_service=delegation_service)


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
    request: Request,
    settings: Settings = Depends(get_settings),
) -> DiagnosticsService:
    delegation_service = getattr(request.app.state, "delegation_service", None)
    if delegation_service is None:
        delegation_service = create_delegation_service(settings)
    return DiagnosticsService(settings=settings, delegation_service=delegation_service)


def get_delegation_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> DelegationService:
    service = getattr(request.app.state, "delegation_service", None)
    if service is not None:
        return service
    return create_delegation_service(settings)


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
