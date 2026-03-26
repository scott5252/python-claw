from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.gateway.deps import create_run_execution_service
from apps.gateway.main import create_app
from src.config.settings import Settings
from src.db.base import Base
from src.db.session import DatabaseSessionManager


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def session_manager(database_url: str) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(database_url)
    Base.metadata.create_all(manager.engine)
    return manager


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        runtime_mode="rule_based",
        dedupe_stale_after_seconds=1,
        messages_page_default_limit=2,
        messages_page_max_limit=3,
        diagnostics_admin_bearer_token="admin-secret",
        diagnostics_internal_service_token="internal-secret",
        diagnostics_page_default_limit=2,
        diagnostics_page_max_limit=3,
    )


@pytest.fixture
def app(settings: Settings, session_manager: DatabaseSessionManager):
    app = create_app(settings=settings, session_manager=session_manager)
    app.state.run_execution_service = create_run_execution_service(settings)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def drain_queue(app, session_manager: DatabaseSessionManager):
    def _drain(*, max_runs: int = 10) -> list[str]:
        processed: list[str] = []
        for _ in range(max_runs):
            with session_manager.session() as db:
                run_id = app.state.run_execution_service.process_next_run(db, worker_id="test-worker")
                db.commit()
            if run_id is None:
                break
            processed.append(run_id)
        return processed

    return _drain
