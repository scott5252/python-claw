from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
        dedupe_stale_after_seconds=1,
        messages_page_default_limit=2,
        messages_page_max_limit=3,
    )


@pytest.fixture
def app(settings: Settings, session_manager: DatabaseSessionManager):
    return create_app(settings=settings, session_manager=session_manager)


@pytest.fixture
def client(app):
    return TestClient(app)
