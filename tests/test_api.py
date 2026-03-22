from __future__ import annotations

def inbound_payload(**overrides):
    payload = {
        "channel_kind": "slack",
        "channel_account_id": "acct-1",
        "external_message_id": "msg-1",
        "sender_id": "sender-1",
        "content": "hello",
        "peer_id": "peer-1",
    }
    payload.update(overrides)
    return payload


def test_inbound_acceptance_and_duplicate_replay(client) -> None:
    first = client.post("/inbound/message", json=inbound_payload())
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["dedupe_status"] == "accepted"

    second = client.post("/inbound/message", json=inbound_payload())
    assert second.status_code == 201
    second_body = second.json()
    assert second_body["dedupe_status"] == "duplicate"
    assert second_body["session_id"] == first_body["session_id"]
    assert second_body["message_id"] == first_body["message_id"]


def test_invalid_routing_tuple_is_rejected(client) -> None:
    response = client.post(
        "/inbound/message",
        json=inbound_payload(peer_id="peer-1", group_id="group-1"),
    )
    assert response.status_code == 400


def test_session_reuse_and_message_history(client) -> None:
    first = client.post("/inbound/message", json=inbound_payload(external_message_id="msg-1", content="one"))
    second = client.post("/inbound/message", json=inbound_payload(external_message_id="msg-2", content="two"))

    session_id = first.json()["session_id"]
    assert second.json()["session_id"] == session_id

    session_response = client.get(f"/sessions/{session_id}")
    assert session_response.status_code == 200
    assert session_response.json()["scope_name"] == "main"

    messages_response = client.get(f"/sessions/{session_id}/messages", params={"limit": 4})
    assert messages_response.status_code == 200
    body = messages_response.json()
    assert [item["content"] for item in body["items"]] == ["Received: one", "two", "Received: two"]


def test_cross_channel_dedupe_identity_isolated(client) -> None:
    first = client.post("/inbound/message", json=inbound_payload(channel_kind="slack"))
    second = client.post("/inbound/message", json=inbound_payload(channel_kind="telegram"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["message_id"] != second.json()["message_id"]
