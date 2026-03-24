from __future__ import annotations

from src.config.settings import Settings
from src.observability.context import ensure_trace_id
from src.observability.failures import classify_failure
from src.observability.logging import build_event
from src.observability.redaction import bounded_preview, redact_value


def test_observability_event_populates_required_fields_and_redacts_secrets() -> None:
    settings = Settings(database_url="sqlite://")
    event = build_event(
        settings=settings,
        event_name="gateway.inbound.accepted",
        component="gateway",
        status="accepted",
        trace_id="trace-1",
        session_id="session-1",
        execution_run_id="run-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="slack",
        channel_account_id="acct-1",
        authorization="Bearer secret",
    )
    assert event["event_name"] == "gateway.inbound.accepted"
    assert event["trace_id"] == "trace-1"
    assert event["authorization"] == "[redacted]"


def test_trace_helper_reuses_existing_trace_id() -> None:
    assert ensure_trace_id("trace-1") == "trace-1"
    assert ensure_trace_id(None)


def test_failure_classification_and_bounded_preview_are_stable() -> None:
    assert classify_failure(error_code="adapter_send_failed") == "delivery_failed"
    assert classify_failure(error_detail="dependency unavailable") == "dependency_unavailable"
    assert bounded_preview("abcdef", enabled=True, max_chars=3) == "abc..."
    assert redact_value("cookie", "secret") == "[redacted]"
