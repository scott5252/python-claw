from __future__ import annotations

import json
from datetime import datetime, timezone

from src.graphs.state import ToolEvent, ToolRequest
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


def test_append_only_runtime_artifacts_are_persisted_in_order(session_manager) -> None:
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
        repository.append_tool_proposal(
            db,
            session_id=session.id,
            request=ToolRequest(
                correlation_id="corr-1",
                capability_name="echo_text",
                arguments={"text": "hello"},
            ),
        )
        repository.append_tool_event(
            db,
            session_id=session.id,
            event=ToolEvent(
                correlation_id="corr-1",
                capability_name="echo_text",
                status="succeeded",
                arguments={"text": "hello"},
                outcome={"content": "hello"},
            ),
        )
        repository.append_outbound_intent(
            db,
            session_id=session.id,
            correlation_id="corr-2",
            payload={"text": "ship it", "channel_kind": "web", "sender_id": "sender"},
        )
        db.commit()

    with session_manager.session() as db:
        artifacts = repository.list_artifacts(db, session_id=session.id)
        assert [artifact.artifact_kind for artifact in artifacts] == [
            "tool_proposal",
            "tool_result",
            "outbound_intent",
        ]
        assert json.loads(artifacts[0].payload_json) == {"arguments": {"text": "hello"}}
        assert json.loads(artifacts[1].payload_json) == {
            "arguments": {"text": "hello"},
            "outcome": {"content": "hello"},
        }
        assert json.loads(artifacts[2].payload_json)["text"] == "ship it"
