from __future__ import annotations

from datetime import datetime, timezone

from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository


def test_get_or_create_session_reuses_canonical_key(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        first = repository.get_or_create_session(db, routing)
        db.commit()

    with session_manager.session() as db:
        second = repository.get_or_create_session(db, routing)
        assert first.id == second.id


def test_message_paging_is_append_ordered(session_manager) -> None:
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )

    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        first = repository.append_message(
            db,
            session,
            role="user",
            content="one",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        second = repository.append_message(
            db,
            session,
            role="user",
            content="two",
            external_message_id="m2",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        third = repository.append_message(
            db,
            session,
            role="user",
            content="three",
            external_message_id="m3",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        db.commit()

    with session_manager.session() as db:
        page = repository.list_messages(db, session_id=session.id, limit=2, before_message_id=None)
        assert [row.id for row in page] == [second.id, third.id]

        next_page = repository.list_messages(db, session_id=session.id, limit=2, before_message_id=second.id)
        assert [row.id for row in next_page] == [first.id]
