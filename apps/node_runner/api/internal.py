from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.execution.contracts import SignedNodeExecRequest

router = APIRouter()


@router.post("/internal/node/exec")
def post_exec(payload: dict, request: Request) -> dict:
    signed = SignedNodeExecRequest.from_payload(payload)
    with request.app.state.session_manager.session() as db:
        decision = request.app.state.node_runner_policy.authorize(db, signed_request=signed)
        if decision.should_execute:
            result = request.app.state.node_runner_executor.execute(
                db,
                record=decision.record,
                request=signed.request,
            )
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
