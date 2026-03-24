from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.policies.service import canonicalize_params, hash_payload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def derive_request_id(
    *,
    execution_run_id: str,
    tool_call_id: str,
    execution_attempt_number: int,
) -> str:
    identity = canonical_json(
        {
            "execution_attempt_number": execution_attempt_number,
            "execution_run_id": execution_run_id,
            "tool_call_id": tool_call_id,
        }
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def preview_text(value: str, limit: int = 2000) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


@dataclass(frozen=True)
class NodeCommandTemplate:
    executable: str
    argv_template: list[str]
    env_allowlist: list[str]
    working_dir: str | None
    workspace_binding_kind: str
    fixed_workspace_key: str | None
    workspace_mount_mode: str
    typed_action_id: str
    sandbox_profile_key: str
    timeout_seconds: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "NodeCommandTemplate":
        return cls(
            executable=payload["executable"],
            argv_template=list(payload.get("argv_template", [])),
            env_allowlist=list(payload.get("env_allowlist", [])),
            working_dir=payload.get("working_dir"),
            workspace_binding_kind=payload["workspace_binding_kind"],
            fixed_workspace_key=payload.get("fixed_workspace_key"),
            workspace_mount_mode=payload["workspace_mount_mode"],
            typed_action_id=payload["typed_action_id"],
            sandbox_profile_key=payload["sandbox_profile_key"],
            timeout_seconds=int(payload["timeout_seconds"]),
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RemoteInvocation:
    arguments: dict[str, Any]
    env: dict[str, str]
    working_dir: str | None
    timeout_seconds: int

    def canonical_params_json(self) -> str:
        return canonicalize_params(
            {
                "arguments": self.arguments,
                "env": self.env,
                "timeout_seconds": self.timeout_seconds,
                "working_dir": self.working_dir,
            }
        )

    def canonical_params_hash(self) -> str:
        return hash_payload(self.canonical_params_json())


def derive_argv(*, template: NodeCommandTemplate, arguments: dict[str, Any]) -> list[str]:
    values = {key: str(value) for key, value in arguments.items()}
    argv = [template.executable]
    for item in template.argv_template:
        try:
            argv.append(item.format_map(values))
        except KeyError as exc:
            raise ValueError(f"missing argv template parameter: {exc.args[0]}") from exc
    return argv


@dataclass(frozen=True)
class NodeExecRequest:
    request_id: str
    execution_run_id: str
    tool_call_id: str
    execution_attempt_number: int
    session_id: str
    message_id: int | None
    agent_id: str
    typed_action_id: str
    approval_id: str
    resource_version_id: str
    resource_payload_hash: str
    canonical_params_json: str
    canonical_params_hash: str
    argv: list[str]
    sandbox_mode: str
    sandbox_key: str
    workspace_root: str
    workspace_mount_mode: str
    issued_at: str
    expires_at: str
    trace_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "NodeExecRequest":
        return cls(**payload)


@dataclass(frozen=True)
class SignedNodeExecRequest:
    key_id: str
    signature: str
    request: NodeExecRequest

    def signed_payload(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "request": self.request.to_payload(),
            "signature": self.signature,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SignedNodeExecRequest":
        return cls(
            key_id=payload["key_id"],
            signature=payload["signature"],
            request=NodeExecRequest.from_payload(payload["request"]),
        )


@dataclass(frozen=True)
class NodeExecutionResult:
    request_id: str
    status: str
    exit_code: int | None
    stdout_preview: str
    stderr_preview: str
    stdout_truncated: bool
    stderr_truncated: bool
    deny_reason: str | None = None


def build_exec_request(
    *,
    execution_run_id: str,
    tool_call_id: str,
    execution_attempt_number: int,
    session_id: str,
    message_id: int | None,
    agent_id: str,
    approval_id: str,
    resource_version_id: str,
    resource_payload_hash: str,
    invocation: RemoteInvocation,
    argv: list[str],
    sandbox_mode: str,
    sandbox_key: str,
    workspace_root: str,
    workspace_mount_mode: str,
    typed_action_id: str,
    ttl_seconds: int,
    trace_id: str | None = None,
    now: datetime | None = None,
) -> NodeExecRequest:
    current_time = now or utc_now()
    return NodeExecRequest(
        request_id=derive_request_id(
            execution_run_id=execution_run_id,
            tool_call_id=tool_call_id,
            execution_attempt_number=execution_attempt_number,
        ),
        execution_run_id=execution_run_id,
        tool_call_id=tool_call_id,
        execution_attempt_number=execution_attempt_number,
        session_id=session_id,
        message_id=message_id,
        agent_id=agent_id,
        typed_action_id=typed_action_id,
        approval_id=approval_id,
        resource_version_id=resource_version_id,
        resource_payload_hash=resource_payload_hash,
        canonical_params_json=invocation.canonical_params_json(),
        canonical_params_hash=invocation.canonical_params_hash(),
        argv=argv,
        sandbox_mode=sandbox_mode,
        sandbox_key=sandbox_key,
        workspace_root=workspace_root,
        workspace_mount_mode=workspace_mount_mode,
        issued_at=current_time.isoformat(),
        expires_at=(current_time + timedelta(seconds=ttl_seconds)).isoformat(),
        trace_id=trace_id,
    )
