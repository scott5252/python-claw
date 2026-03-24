from __future__ import annotations

import json
import logging
from typing import Any

from src.config.settings import Settings
from src.observability.redaction import bounded_preview, redact_value


def build_event(
    *,
    settings: Settings,
    event_name: str,
    component: str,
    status: str,
    trace_id: str | None,
    session_id: str | None = None,
    execution_run_id: str | None = None,
    message_id: int | None = None,
    agent_id: str | None = None,
    channel_kind: str | None = None,
    channel_account_id: str | None = None,
    duration_ms: int | None = None,
    content: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    event = {
        "event_name": event_name,
        "trace_id": trace_id,
        "session_id": session_id,
        "execution_run_id": execution_run_id,
        "message_id": message_id,
        "agent_id": agent_id,
        "channel_kind": channel_kind,
        "channel_account_id": channel_account_id,
        "component": component,
        "status": status,
        "duration_ms": duration_ms,
    }
    if content is not None:
        event["content_preview"] = bounded_preview(
            content,
            enabled=settings.observability_log_content_preview,
            max_chars=settings.observability_log_content_preview_chars,
        )
    for key, value in fields.items():
        event[key] = redact_value(key, value)
    return event


def emit_event(logger: logging.Logger, *, level: int = logging.INFO, event: dict[str, Any]) -> None:
    logger.log(level, json.dumps(event, sort_keys=True, default=str))
