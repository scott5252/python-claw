from __future__ import annotations

import json

from src.sessions.repository import SessionRepository


OPERATOR_HEADERS = {"Authorization": "Bearer admin-secret", "X-Operator-Id": "operator-1"}


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
    assert first_body["trace_id"]

    second = client.post("/inbound/message", json=inbound_payload())
    assert second.status_code == 202
    second_body = second.json()
    assert second_body["dedupe_status"] == "duplicate"
    assert second_body["session_id"] == first_body["session_id"]
    assert second_body["message_id"] == first_body["message_id"]
    assert second_body["run_id"] == first_body["run_id"]
    assert second_body["trace_id"] == first_body["trace_id"]


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

    session_response = client.get(f"/sessions/{session_id}", headers=OPERATOR_HEADERS)
    assert session_response.status_code == 200
    assert session_response.json()["scope_name"] == "main"

    messages_response = client.get(f"/sessions/{session_id}/messages", headers=OPERATOR_HEADERS, params={"limit": 4})
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

    pending = client.get(f"/sessions/{session_id}/governance/pending", headers=OPERATOR_HEADERS)
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
    trace_id = response.json()["trace_id"]

    run = client.get(f"/runs/{run_id}", headers=OPERATOR_HEADERS)
    assert run.status_code == 200
    assert run.json()["id"] == run_id
    assert run.json()["status"] == "queued"
    assert run.json()["trace_id"] == trace_id

    session_runs = client.get(f"/sessions/{session_id}/runs", headers=OPERATOR_HEADERS)
    assert session_runs.status_code == 200
    assert session_runs.json()["items"][0]["id"] == run_id
    assert session_runs.json()["items"][0]["trace_id"] == trace_id


def test_inbound_accepts_canonical_attachments_without_inline_normalization(client, session_manager, tmp_path) -> None:
    attachment_path = tmp_path / "attachment.txt"
    attachment_path.write_text("hello attachment")
    response = client.post(
        "/inbound/message",
        json=inbound_payload(
            attachments=[
                {
                    "source_url": attachment_path.resolve().as_uri(),
                    "mime_type": "text/plain",
                    "filename": "attachment.txt",
                    "provider_metadata": {"provider": "test"},
                }
            ]
        ),
    )
    assert response.status_code == 202

    with session_manager.session() as db:
        rows = SessionRepository().list_inbound_attachments(db, message_id=response.json()["message_id"])
        assert len(rows) == 1
        assert rows[0].mime_type == "text/plain"
        assert json.loads(rows[0].provider_metadata_json) == {"provider": "test"}


def test_inbound_rejects_attachment_without_required_fields(client) -> None:
    response = client.post(
        "/inbound/message",
        json=inbound_payload(
            attachments=[
                {
                    "source_url": "",
                    "mime_type": "text/plain",
                }
            ]
        ),
    )
    assert response.status_code == 422


def test_inbound_rejects_unbounded_provider_metadata(client) -> None:
    response = client.post(
        "/inbound/message",
        json=inbound_payload(
            attachments=[
                {
                    "source_url": "file:///tmp/example.txt",
                    "mime_type": "text/plain",
                    "provider_metadata": {"huge": "x" * 2500},
                }
            ]
        ),
    )
    assert response.status_code == 422


def test_health_live_is_open_and_ready_requires_operator_auth(client) -> None:
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    ready = client.get("/health/ready")
    assert ready.status_code == 401


def test_ready_accepts_admin_bearer_and_reports_dependency_checks(client) -> None:
    ready = client.get("/health/ready", headers={"Authorization": "Bearer admin-secret"})
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ok"
    assert any(check["name"] == "postgresql" for check in body["checks"])


def test_diagnostics_routes_deny_by_default_and_support_paging(client, drain_queue) -> None:
    one = client.post("/inbound/message", json=inbound_payload(external_message_id="diag-1", content="one"))
    two = client.post("/inbound/message", json=inbound_payload(external_message_id="diag-2", content="two"))
    three = client.post("/inbound/message", json=inbound_payload(external_message_id="diag-3", content="three"))
    drain_queue()

    unauthorized = client.get("/diagnostics/runs")
    assert unauthorized.status_code == 401

    headers = {"X-Internal-Service-Token": "internal-secret"}
    page_one = client.get("/diagnostics/runs", headers=headers, params={"limit": 2})
    assert page_one.status_code == 200
    body_one = page_one.json()
    assert body_one["limit"] == 2
    assert len(body_one["items"]) == 2
    assert body_one["has_more"] is True
    assert body_one["next_cursor"]

    page_two = client.get("/diagnostics/runs", headers=headers, params={"cursor": body_one["next_cursor"], "limit": 2})
    assert page_two.status_code == 200
    body_two = page_two.json()
    assert len(body_two["items"]) >= 1

    run_id = one.json()["run_id"]
    detail = client.get(f"/diagnostics/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["run"]["id"] == run_id

    continuity = client.get(
        f"/diagnostics/sessions/{one.json()['session_id']}/continuity",
        headers=headers,
    )
    assert continuity.status_code == 200
    assert continuity.json()["capability_status"] == "enabled"


def test_operator_only_reads_reject_internal_service_callers(client) -> None:
    inbound = client.post("/inbound/message", json=inbound_payload(external_message_id="operator-only-1"))
    session_id = inbound.json()["session_id"]

    response = client.get(
        f"/sessions/{session_id}",
        headers={"X-Internal-Service-Token": "internal-secret"},
    )
    assert response.status_code == 403


def test_diagnostics_delivery_and_attachment_views_are_sanitized(client, drain_queue, session_manager) -> None:
    attachment_response = client.post(
        "/inbound/message",
        json=inbound_payload(
            external_message_id="diag-attach",
            attachments=[
                {
                    "source_url": "file:///tmp/missing-diagnostic.txt",
                    "mime_type": "text/plain",
                }
            ],
        ),
    )
    assert attachment_response.status_code == 202
    drain_queue(max_runs=1)

    headers = {"Authorization": "Bearer admin-secret"}
    attachments = client.get("/diagnostics/attachments", headers=headers)
    assert attachments.status_code == 200
    assert attachments.json()["capability_status"] == "enabled"

    deliveries = client.get("/diagnostics/deliveries", headers=headers)
    assert deliveries.status_code == 200
    assert "items" in deliveries.json()


def test_webchat_sse_replays_durable_stream_events(client, drain_queue) -> None:
    response = client.post(
        "/providers/webchat/accounts/acct/messages",
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
        json={
            "actor_id": "user-1",
            "content": "hello streamed world",
            "peer_id": "peer-1",
            "stream_id": "stream-1",
        },
    )
    assert response.status_code == 202
    drain_queue()

    stream = client.get(
        "/providers/webchat/accounts/acct/stream",
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
        params={"stream_id": "stream-1"},
    )
    assert stream.status_code == 200
    body = stream.text
    assert "event: delivery" in body
    assert '"event_kind":"stream_started"' in body
    assert '"event_kind":"text_delta"' in body
    assert '"event_kind":"stream_finalized"' in body

    first_id = None
    for line in body.splitlines():
        if line.startswith("id: "):
            first_id = line.split(": ", 1)[1]
            break
    assert first_id is not None

    replay = client.get(
        "/providers/webchat/accounts/acct/stream",
        headers={
            "X-Webchat-Client-Token": "fake-webchat-token",
            "Last-Event-ID": first_id,
        },
        params={"stream_id": "stream-1"},
    )
    assert replay.status_code == 200
    assert f"id: {first_id}" not in replay.text
