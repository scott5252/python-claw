from __future__ import annotations

from fastapi import FastAPI

from apps.node_runner.api.internal import router as internal_router
from apps.node_runner.executor import NodeRunnerExecutor
from apps.node_runner.policy import NodeRunnerPolicy
from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings, get_settings
from src.db.session import DatabaseSessionManager
from src.execution.audit import ExecutionAuditRepository
from src.sandbox.service import SandboxService
from src.security.signing import SigningService


def create_app(
    *,
    settings: Settings | None = None,
    session_manager: DatabaseSessionManager | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    manager = session_manager or DatabaseSessionManager(resolved_settings.database_url)
    capabilities_repository = CapabilitiesRepository()
    audit_repository = ExecutionAuditRepository()
    signing_service = SigningService({resolved_settings.node_runner_signing_key_id: resolved_settings.node_runner_signing_secret})
    app = FastAPI(title="python-claw-node-runner")
    app.state.settings = resolved_settings
    app.state.session_manager = manager
    app.state.db_provider = manager.session
    app.state.audit_repository = audit_repository
    app.state.node_runner_policy = NodeRunnerPolicy(
        settings=resolved_settings,
        signing_service=signing_service,
        capabilities_repository=capabilities_repository,
        sandbox_service=SandboxService(
            settings=resolved_settings,
            capabilities_repository=capabilities_repository,
        ),
        audit_repository=audit_repository,
    )
    app.state.node_runner_executor = NodeRunnerExecutor(audit_repository=audit_repository)
    app.include_router(internal_router)
    return app


app = create_app()
