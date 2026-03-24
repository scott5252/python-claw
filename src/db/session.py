from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class DatabaseSessionManager:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        engine_kwargs = {
            "future": True,
            "connect_args": connect_args,
        }
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            # Share a single in-memory SQLite database across threads so
            # request/worker sessions see the same schema and rows.
            engine_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(database_url, **engine_kwargs)
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self._session_factory()
        try:
            yield db
        finally:
            db.close()
