from __future__ import annotations

import json

from src.sessions.repository import SessionRepository


def _admin_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer admin-secret",
        "X-Operator-Id": "op-1",
    }


def _inbound_payload(**overrides):
    payload = {
        "channel_kind": "webchat",
        "channel_account_id": "acct",
        "external_message_id": "spec-016-msg-1",
        "sender_id": "user-1",
        "content": "hello",
        "peer_id": "peer-1",
    }
    payload.update(overrides)
    return payload


def test_takeover_blocks_new_inbound_runs_and_resume_releases_them(client, session_manager, drain_queue) -> None:
    first = client.post("/inbound/message", json=_inbound_payload())
    assert first.status_code == 202
    session_id = first.json()["session_id"]

    takeover = client.post(
        f"/sessions/{session_id}/takeover",
        headers=_admin_headers(),
        json={"expected_collaboration_version": 1, "reason": "human handoff"},
    )
    assert takeover.status_code == 200
    assert takeover.json()["automation_state"] == "human_takeover"
    assert takeover.json()["collaboration_version"] == 2

    second = client.post(
        "/inbound/message",
        json=_inbound_payload(external_message_id="spec-016-msg-2", content="please wait"),
    )
    assert second.status_code == 202
    assert second.json()["status"] == "blocked"

    blocked_run_id = second.json()["run_id"]
    with session_manager.session() as db:
        blocked_run = SessionRepository()
        run = client.app.state.session_service.jobs_repository.get_execution_run(db, blocked_run_id)
        assert run is not None
        assert run.status == "blocked"
        assert run.blocked_reason == "automation_state:human_takeover"

    resume = client.post(
        f"/sessions/{session_id}/resume",
        headers=_admin_headers(),
        json={"expected_collaboration_version": 2, "reason": "resume automation"},
    )
    assert resume.status_code == 200
    assert resume.json()["automation_state"] == "assistant_active"

    drain_queue()
    with session_manager.session() as db:
        run = client.app.state.session_service.jobs_repository.get_execution_run(db, blocked_run_id)
        assert run is not None
        assert run.status == "completed"


def test_takeover_after_enqueue_suppresses_dispatch_without_persisting_assistant_transcript(client, session_manager) -> None:
    response = client.post("/inbound/message", json=_inbound_payload(external_message_id="spec-016-race", content="hello race"))
    assert response.status_code == 202
    session_id = response.json()["session_id"]
    run_id = response.json()["run_id"]

    takeover = client.post(
        f"/sessions/{session_id}/takeover",
        headers=_admin_headers(),
        json={"expected_collaboration_version": 1, "reason": "operator jumped in"},
    )
    assert takeover.status_code == 200

    with session_manager.session() as db:
        processed = client.app.state.run_execution_service.process_next_run(db, worker_id="worker-1")
        db.commit()
        assert processed == run_id

    with session_manager.session() as db:
        repository = SessionRepository()
        messages = repository.list_messages(db, session_id=session_id, limit=20, before_message_id=None)
        deliveries = [item for item in repository.list_outbound_deliveries(db, session_id=session_id) if item.execution_run_id == run_id]
        events = repository.list_collaboration_events(db, session_id=session_id)

    assert [message.role for message in messages] == ["user"]
    assert len(deliveries) == 1
    assert deliveries[0].status == "suppressed"
    assert deliveries[0].completion_status == "suppressed:human_takeover"
    assert any(event.event_kind == "dispatch_suppressed" for event in events)


def test_structured_approval_prompt_is_materialized_and_admin_decision_updates_it(client, drain_queue) -> None:
    response = client.post(
        "/inbound/message",
        json=_inbound_payload(external_message_id="spec-016-approval", content="send hello channel"),
    )
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    drain_queue()

    pending = client.get(f"/sessions/{session_id}/governance/pending")
    assert pending.status_code == 200
    proposal_id = pending.json()[0]["proposal_id"]

    prompts = client.get(f"/sessions/{session_id}/approval-prompts", headers=_admin_headers())
    assert prompts.status_code == 200
    assert len(prompts.json()) == 1
    prompt = prompts.json()[0]
    payload = json.loads(prompt["presentation_payload_json"])
    assert payload["proposal_id"] == proposal_id
    assert payload["actions"]["approve"]["token"]
    assert prompt["status"] == "pending"

    decision = client.post(
        f"/sessions/{session_id}/governance/{proposal_id}/decision",
        headers=_admin_headers(),
        json={"decision": "approve"},
    )
    assert decision.status_code == 200
    assert decision.json()["outcome"] == "approved"

    prompts_after = client.get(f"/sessions/{session_id}/approval-prompts", headers=_admin_headers())
    assert prompts_after.status_code == 200
    assert prompts_after.json()[0]["status"] == "approved"


def test_webchat_approval_action_accepts_prompt_token_and_normalizes_wrapped_token(client, drain_queue) -> None:
    response = client.post(
        "/providers/webchat/accounts/acct/messages",
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
        json={
            "actor_id": "web-user-2",
            "content": "send hello channel",
            "peer_id": "web-user-2",
            "stream_id": "demo016-token-stream",
        },
    )
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    drain_queue()

    prompts = client.get(
        "/providers/webchat/accounts/acct/approval-prompts",
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
        params={"stream_id": "demo016-token-stream"},
    )
    assert prompts.status_code == 200
    prompt_payload = json.loads(prompts.json()[0]["presentation_payload_json"])
    approve_token = prompt_payload["actions"]["approve"]["token"]

    decision = client.post(
        "/providers/webchat/accounts/acct/approval-actions",
        headers={"X-Webchat-Client-Token": "fake-webchat-token"},
        json={"decision": "approve", "token": json.dumps(approve_token)},
    )
    assert decision.status_code == 200
    assert decision.json()["outcome"] == "approved"

    prompts_after = client.get(f"/sessions/{session_id}/approval-prompts", headers=_admin_headers())
    assert prompts_after.status_code == 200
    assert prompts_after.json()[0]["status"] == "approved"
