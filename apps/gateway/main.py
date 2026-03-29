from fastapi import FastAPI

from apps.gateway.deps import (
    bootstrap_runtime_state,
    create_delegation_service,
    create_collaboration_service,
    create_approval_decision_service,
    get_quota_service,
    create_run_execution_service,
    create_scheduler_service,
    create_session_service,
)
from apps.gateway.api.admin import router as admin_router
from apps.gateway.api.health import router as health_router
from apps.gateway.api.inbound import router as inbound_router
from apps.gateway.api.slack import router as slack_router
from apps.gateway.api.telegram import router as telegram_router
from apps.gateway.api.webchat import router as webchat_router
from src.config.settings import Settings, get_settings
from src.db.base import Base
from src.db.session import DatabaseSessionManager
from src.policies.quota import QuotaService


def create_app(
    *,
    settings: Settings | None = None,
    session_manager: DatabaseSessionManager | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title=resolved_settings.app_name)
    app.state.settings = resolved_settings
    app.state.session_manager = session_manager or DatabaseSessionManager(resolved_settings.database_url)
    Base.metadata.create_all(app.state.session_manager.engine)
    bootstrap_runtime_state(settings=resolved_settings, session_manager=app.state.session_manager)
    app.state.delegation_service = create_delegation_service(resolved_settings)
    app.state.collaboration_service = create_collaboration_service(resolved_settings)
    app.state.approval_decision_service = create_approval_decision_service(resolved_settings)
    app.state.session_service = create_session_service(resolved_settings)
    app.state.run_execution_service = create_run_execution_service(
        resolved_settings,
        delegation_service=app.state.delegation_service,
    )
    app.state.scheduler_service = create_scheduler_service(resolved_settings)
    app.state.quota_service = QuotaService()
    app.include_router(health_router)
    app.include_router(inbound_router)
    app.include_router(slack_router)
    app.include_router(telegram_router)
    app.include_router(webchat_router)
    app.include_router(admin_router)
    return app


app = create_app()
