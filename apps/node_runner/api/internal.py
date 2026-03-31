from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.db.models import NodeExecutionStatus
from src.execution.contracts import SignedNodeExecRequest

router = APIRouter()


def _require_internal_transport_auth(request: Request) -> None:
    settings = request.app.state.settings
    if settings.node_runner_mode != "http":
        return
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="internal authorization required")
    token = authorization.removeprefix("Bearer ").strip()
    if token not in settings.node_runner_transport_tokens():
        raise HTTPException(status_code=401, detail="internal authorization required")


@router.post("/internal/node/exec")
def post_exec(payload: dict, request: Request) -> dict:
    _require_internal_transport_auth(request)
    signed = SignedNodeExecRequest.from_payload(payload)
    with request.app.state.session_manager.session() as db:
        decision = request.app.state.node_runner_policy.authorize(db, signed_request=signed)
        if decision.should_execute:
            try:
                result = request.app.state.node_runner_executor.execute(
                    db,
                    record=decision.record,
                    request=signed.request,
                )
            except Exception as exc:
                record = request.app.state.audit_repository.mark_finished(
                    db,
                    record=decision.record,
                    status=NodeExecutionStatus.FAILED.value,
                    exit_code=None,
                    stdout="",
                    stderr=str(exc),
                )
                result = {
                    "request_id": record.request_id,
                    "status": record.status,
                    "exit_code": record.exit_code,
                    "stdout_preview": record.stdout_preview,
                    "stderr_preview": record.stderr_preview,
                    "stdout_truncated": record.stdout_truncated,
                    "stderr_truncated": record.stderr_truncated,
                    "deny_reason": str(exc),
                }
        else:
            record = decision.record
            result = {
                "request_id": record.request_id,
                "status": record.status,
                "exit_code": record.exit_code,
                "stdout_preview": record.stdout_preview,
                "stderr_preview": record.stderr_preview,
                "stdout_truncated": record.stdout_truncated,
                "stderr_truncated": record.stderr_truncated,
                "deny_reason": record.deny_reason,
            }
        db.commit()
        return result if isinstance(result, dict) else result.__dict__


@router.get("/internal/node/exec/{request_id}")
def get_exec(request_id: str, request: Request) -> dict:
    _require_internal_transport_auth(request)
    with request.app.state.session_manager.session() as db:
        record = request.app.state.audit_repository.get_by_request_id(db, request_id=request_id)
        if record is None:
            raise HTTPException(status_code=404, detail="request not found")
        return {
            "request_id": record.request_id,
            "status": record.status,
            "exit_code": record.exit_code,
            "stdout_preview": record.stdout_preview,
            "stderr_preview": record.stderr_preview,
            "stdout_truncated": record.stdout_truncated,
            "stderr_truncated": record.stderr_truncated,
            "deny_reason": record.deny_reason,
        }
