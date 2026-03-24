from __future__ import annotations

from threading import Thread

from src.db.base import Base
from src.db.models import SessionRecord
from src.db.session import DatabaseSessionManager


def test_in_memory_sqlite_is_shared_across_threads() -> None:
    manager = DatabaseSessionManager("sqlite:///:memory:")
    Base.metadata.create_all(manager.engine)

    def write_row() -> None:
        with manager.session() as db:
            db.add(
                SessionRecord(
                    session_key="session-key",
                    channel_kind="slack",
                    channel_account_id="acct-1",
                    scope_kind="direct",
                    peer_id="peer-1",
                    group_id=None,
                    scope_name="main",
                )
            )
            db.commit()

    writer = Thread(target=write_row)
    writer.start()
    writer.join()

    with manager.session() as db:
        assert db.query(SessionRecord).count() == 1
