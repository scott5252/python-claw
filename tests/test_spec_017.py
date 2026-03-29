from __future__ import annotations

from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from apps.node_runner.main import create_app as create_node_runner_app
from src.config.settings import Settings
from src.db.base import Base
from src.db.session import DatabaseSessionManager
from src.observability.redaction import redact_value
from src.sessions.repository import SessionRepository


def _make_manager(tmp_path) -> DatabaseSessionManager:
    manager = DatabaseSessionManager(f"sqlite:///{tmp_path / 'spec017.db'}")
    Base.metadata.create_all(manager.engine)
    return manager


def _build_gateway_client(tmp_path, **settings_overrides) -> tuple[TestClient, DatabaseSessionManager]:
    manager = _make_manager(tmp_path)
    settings = Settings(
        database_url=str(manager.engine.url),
        runtime_mode="rule_based",
        diagnostics_admin_bearer_token="admin-secret",
        diagnostics_internal_service_token="internal-secret",
        operator_auth_bearer_token="admin-secret",
        internal_service_auth_token="internal-secret",
        **settings_overrides,
    )
    app = create_app(settings=settings, session_manager=manager)
    return TestClient(app), manager


def _inbound_payload(**overrides):
    payload = {
        "channel_kind": "slack",
        "channel_account_id": "acct-1",
        "external_message_id": "spec017-msg-1",
        "sender_id": "sender-1",
        "content": "hello",
        "peer_id": "peer-1",
    }
    payload.update(overrides)
    return payload


def test_shared_auth_matrix_enforces_operator_vs_internal_read_boundaries(tmp_path) -> None:
    client, _ = _build_gateway_client(tmp_path)
    accepted = client.post("/inbound/message", json=_inbound_payload())
    session_id = accepted.json()["session_id"]

    live = client.get("/health/live")
    assert live.status_code == 200

    ready = client.get("/health/ready", headers={"X-Internal-Service-Token": "internal-secret"})
    assert ready.status_code == 200

    diagnostics = client.get("/diagnostics/runs", headers={"X-Internal-Service-Token": "internal-secret"})
    assert diagnostics.status_code == 200

    session = client.get(f"/sessions/{session_id}", headers={"X-Internal-Service-Token": "internal-secret"})
    assert session.status_code == 403

    session = client.get(
        f"/sessions/{session_id}",
        headers={"Authorization": "Bearer admin-secret", "X-Operator-Id": "operator-1"},
    )
    assert session.status_code == 200


def test_operator_mutations_require_real_operator_principal(tmp_path) -> None:
    client, _ = _build_gateway_client(tmp_path)
    accepted = client.post("/inbound/message", json=_inbound_payload(external_message_id="spec017-msg-2"))
    session_id = accepted.json()["session_id"]

    response = client.post(
        f"/sessions/{session_id}/notes",
        json={"note_kind": "operator", "body": "test"},
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert response.status_code == 400

    forbidden = client.post(
        f"/sessions/{session_id}/notes",
        json={"note_kind": "operator", "body": "test"},
        headers={"X-Internal-Service-Token": "internal-secret"},
    )
    assert forbidden.status_code == 403


def test_rate_limit_rejects_inbound_before_durable_side_effects(tmp_path) -> None:
    client, manager = _build_gateway_client(
        tmp_path,
        rate_limits_enabled=True,
        inbound_requests_per_minute_per_channel_account=1,
    )

    first = client.post("/inbound/message", json=_inbound_payload(external_message_id="spec017-rate-1"))
    second = client.post("/inbound/message", json=_inbound_payload(external_message_id="spec017-rate-2"))

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.headers["Retry-After"]

    with manager.session() as db:
        repository = SessionRepository()
        session = repository.get_session(db, first.json()["session_id"])
        assert session is not None
        messages = repository.list_messages(db, session_id=first.json()["session_id"], limit=10, before_message_id=None)
        assert len(messages) == 1


def test_admin_quota_applies_to_operator_reads(tmp_path) -> None:
    client, _ = _build_gateway_client(
        tmp_path,
        rate_limits_enabled=True,
        admin_requests_per_minute_per_operator=1,
    )
    client.post("/inbound/message", json=_inbound_payload(external_message_id="spec017-admin-rate-1"))
    headers = {"Authorization": "Bearer admin-secret", "X-Operator-Id": "operator-1"}

    first = client.get("/diagnostics/runs", headers=headers)
    second = client.get("/diagnostics/runs", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429


def test_secret_redaction_covers_new_production_auth_fields() -> None:
    assert redact_value("operator_auth_bearer_token", "secret") == "[redacted]"
    assert redact_value("node_runner_internal_bearer_token", "secret") == "[redacted]"
    assert redact_value("llm_api_key", "secret") == "[redacted]"


def test_node_runner_http_mode_requires_transport_auth(tmp_path) -> None:
    manager = _make_manager(tmp_path)
    settings = Settings(
        database_url=str(manager.engine.url),
        runtime_mode="rule_based",
        node_runner_mode="http",
        node_runner_base_url="http://node-runner.local",
        node_runner_internal_bearer_token="node-secret",
    )
    app = create_node_runner_app(settings=settings, session_manager=manager)
    client = TestClient(app)

    response = client.post("/internal/node/exec", json={"request": {}, "key_id": "kid", "signature": "sig"})
    assert response.status_code == 401
