from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "node_runner_signing_secret",
    "node_runner_previous_signing_secret",
    "node_runner_internal_bearer_token",
    "node_runner_previous_internal_bearer_token",
    "diagnostics_admin_bearer_token",
    "diagnostics_internal_service_token",
    "operator_auth_bearer_token",
    "previous_operator_auth_bearer_token",
    "internal_service_auth_token",
    "previous_internal_service_auth_token",
    "outbound_token",
    "signing_secret",
    "verification_token",
    "webhook_secret",
    "webchat_client_token",
    "llm_api_key",
}


def redact_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if any(marker in lowered_key for marker in ("secret", "token", "authorization", "api_key", "password", "cookie")):
        return "[redacted]"
    if lowered_key in SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {nested_key: redact_value(nested_key, nested_value) for nested_key, nested_value in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def bounded_preview(value: str | None, *, enabled: bool, max_chars: int) -> str | None:
    if value is None or not enabled:
        return None
    trimmed = value.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return f"{trimmed[:max_chars]}..."
