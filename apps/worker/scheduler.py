from __future__ import annotations

from datetime import datetime, timezone

from apps.gateway.deps import create_scheduler_service
from src.config.settings import Settings, get_settings
from src.db.session import DatabaseSessionManager


def submit_job_once(*, job_key: str, scheduled_for: datetime | None = None, settings: Settings | None = None) -> str:
    resolved_settings = settings or get_settings()
    manager = DatabaseSessionManager(resolved_settings.database_url)
    scheduler_service = create_scheduler_service(resolved_settings)
    fire_time = scheduled_for or datetime.now(timezone.utc)
    with manager.session() as db:
        run_id = scheduler_service.submit_due_job(db, job_key=job_key, scheduled_for=fire_time)
        db.commit()
        return run_id
