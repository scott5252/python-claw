from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models import NodeExecutionStatus
from src.execution.audit import ExecutionAuditRepository
from src.execution.contracts import NodeExecRequest, NodeExecutionResult


@dataclass
class NodeRunnerExecutor:
    audit_repository: ExecutionAuditRepository

    def execute(
        self,
        db: Session,
        *,
        record,
        request: NodeExecRequest,
    ) -> NodeExecutionResult:
        self.audit_repository.mark_running(db, record=record)
        workspace_root = Path(request.workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                request.argv,
                cwd=request.workspace_root,
                capture_output=True,
                text=True,
                shell=False,
                timeout=max(1, int(json.loads(request.canonical_params_json)["timeout_seconds"])),
            )
        except subprocess.TimeoutExpired as exc:
            record = self.audit_repository.mark_finished(
                db,
                record=record,
                status=NodeExecutionStatus.TIMED_OUT.value,
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
            )
            return NodeExecutionResult(
                request_id=request.request_id,
                status=record.status,
                exit_code=record.exit_code,
                stdout_preview=record.stdout_preview,
                stderr_preview=record.stderr_preview,
                stdout_truncated=record.stdout_truncated,
                stderr_truncated=record.stderr_truncated,
                deny_reason="execution timed out",
            )

        status = NodeExecutionStatus.COMPLETED.value if completed.returncode == 0 else NodeExecutionStatus.FAILED.value
        record = self.audit_repository.mark_finished(
            db,
            record=record,
            status=status,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        return NodeExecutionResult(
            request_id=request.request_id,
            status=record.status,
            exit_code=record.exit_code,
            stdout_preview=record.stdout_preview,
            stderr_preview=record.stderr_preview,
            stdout_truncated=record.stdout_truncated,
            stderr_truncated=record.stderr_truncated,
            deny_reason=record.deny_reason,
        )
