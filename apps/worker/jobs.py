from __future__ import annotations

from apps.gateway.deps import create_run_execution_service
from src.config.settings import Settings, get_settings
from src.db.session import DatabaseSessionManager


def run_once(*, settings: Settings | None = None) -> str | None:
    resolved_settings = settings or get_settings()
    session_manager = DatabaseSessionManager(resolved_settings.database_url)
    service = create_run_execution_service(resolved_settings)
    with session_manager.session() as db:
        run_id = service.process_next_run(db)
        db.commit()
        return run_id
