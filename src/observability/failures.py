from __future__ import annotations


def classify_failure(*, error_code: str | None = None, error_detail: str | None = None, exc: Exception | None = None) -> str:
    detail = " ".join(part for part in [error_code, error_detail, str(exc) if exc is not None else None] if part).lower()
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
