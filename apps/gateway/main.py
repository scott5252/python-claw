from fastapi import FastAPI

from apps.gateway.deps import create_run_execution_service, create_scheduler_service, create_session_service
from apps.gateway.api.admin import router as admin_router
from apps.gateway.api.health import router as health_router
from apps.gateway.api.inbound import router as inbound_router
from apps.gateway.api.slack import router as slack_router
from apps.gateway.api.telegram import router as telegram_router
from apps.gateway.api.webchat import router as webchat_router
from src.config.settings import Settings, get_settings
from src.db.session import DatabaseSessionManager


def create_app(
    *,
    settings: Settings | None = None,
    session_manager: DatabaseSessionManager | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title=resolved_settings.app_name)
    app.state.settings = resolved_settings
    app.state.session_manager = session_manager or DatabaseSessionManager(resolved_settings.database_url)
    app.state.session_service = create_session_service(resolved_settings)
    app.state.run_execution_service = create_run_execution_service(resolved_settings)
    app.state.scheduler_service = create_scheduler_service(resolved_settings)
    app.include_router(health_router)
    app.include_router(inbound_router)
    app.include_router(slack_router)
    app.include_router(telegram_router)
    app.include_router(webchat_router)
    app.include_router(admin_router)
    return app


app = create_app()
