from __future__ import annotations


def classify_failure(*, error_code: str | None = None, error_detail: str | None = None, exc: Exception | None = None) -> str:
    detail = " ".join(part for part in [error_code, error_detail, str(exc) if exc is not None else None] if part).lower()
    if "provider_timeout" in detail or "provider timed out" in detail or "provider timeout" in detail:
        return "timeout"
    if "provider_auth" in detail or "provider authentication failed" in detail:
        return "dependency_unavailable"
    if "provider_rate_limited" in detail or "provider rate limited" in detail:
        return "dependency_unavailable"
    if "provider_unavailable" in detail or "provider unavailable" in detail:
        return "dependency_unavailable"
    if (
        "provider_malformed_response" in detail
        or "provider malformed response" in detail
        or "malformed_tool_payload" in detail
        or "provider_tool_schema_error" in detail
        or "provider tool schema error" in detail
    ):
        return "validation"
    if "invalid_tool_arguments" in detail or "invalid arguments for `" in detail:
        return "validation"
    if "timeout" in detail:
        return "timeout"
    if "approval" in detail:
        return "approval_missing"
    if "policy" in detail or "denied" in detail:
        return "policy_denied"
    if "validation" in detail:
        return "validation"
    if "delivery" in detail or "adapter_send_failed" in detail:
        return "delivery_failed"
    if "dependency" in detail or "connection" in detail or "unavailable" in detail:
        return "dependency_unavailable"
    return "unexpected_internal"
