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
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["dedupe_status"] == "accepted"
    assert first_body["status"] == "queued"
    assert first_body["run_id"]

    second = client.post("/inbound/message", json=inbound_payload())
    assert second.status_code == 202
    second_body = second.json()
    assert second_body["dedupe_status"] == "duplicate"
    assert second_body["session_id"] == first_body["session_id"]
    assert second_body["message_id"] == first_body["message_id"]
    assert second_body["run_id"] == first_body["run_id"]


def test_invalid_routing_tuple_is_rejected(client) -> None:
    response = client.post(
        "/inbound/message",
        json=inbound_payload(peer_id="peer-1", group_id="group-1"),
    )
    assert response.status_code == 400


def test_session_reuse_and_message_history(client, drain_queue) -> None:
    first = client.post("/inbound/message", json=inbound_payload(external_message_id="msg-1", content="one"))
    second = client.post("/inbound/message", json=inbound_payload(external_message_id="msg-2", content="two"))
    drain_queue()

    session_id = first.json()["session_id"]
    assert second.json()["session_id"] == session_id

    session_response = client.get(f"/sessions/{session_id}")
    assert session_response.status_code == 200
    assert session_response.json()["scope_name"] == "main"

    messages_response = client.get(f"/sessions/{session_id}/messages", params={"limit": 4})
    assert messages_response.status_code == 200
    body = messages_response.json()
    contents = [item["content"] for item in body["items"]]
    assert contents[-2:] == ["Received: one", "Received: two"]
    assert "two" in contents


def test_cross_channel_dedupe_identity_isolated(client) -> None:
    first = client.post("/inbound/message", json=inbound_payload(channel_kind="slack"))
    second = client.post("/inbound/message", json=inbound_payload(channel_kind="telegram"))

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["message_id"] != second.json()["message_id"]


def test_pending_governance_endpoint_returns_structured_items(client, drain_queue) -> None:
    response = client.post(
        "/inbound/message",
        json=inbound_payload(
            external_message_id="msg-governed-1",
            content="send hello channel",
        ),
    )
    assert response.status_code == 202
    drain_queue()
    session_id = response.json()["session_id"]

    pending = client.get(f"/sessions/{session_id}/governance/pending")
    assert pending.status_code == 200
    body = pending.json()
    assert len(body) == 1
    assert body[0]["capability_name"] == "send_message"
    assert body[0]["typed_action_id"] == "tool.send_message"
    assert body[0]["canonical_params"] == {"text": "hello channel"}
    assert body[0]["next_action"].startswith("approve ")


def test_run_diagnostics_endpoints(client) -> None:
    response = client.post("/inbound/message", json=inbound_payload())
    run_id = response.json()["run_id"]
    session_id = response.json()["session_id"]

    run = client.get(f"/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["id"] == run_id
    assert run.json()["status"] == "queued"

    session_runs = client.get(f"/sessions/{session_id}/runs")
    assert session_runs.status_code == 200
    assert session_runs.json()["items"][0]["id"] == run_id
