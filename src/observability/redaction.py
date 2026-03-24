from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "node_runner_signing_secret",
    "diagnostics_admin_bearer_token",
    "diagnostics_internal_service_token",
}


def redact_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS:
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
