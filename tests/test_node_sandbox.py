from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.node_runner.main import create_app as create_node_runner_app
from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.execution.contracts import (
    NodeCommandTemplate,
    NodeExecutionResult,
    RemoteInvocation,
    build_exec_request,
    derive_argv,
    derive_request_id,
)
from src.execution.runtime import RemoteExecutionRuntime
from src.graphs.state import ToolRuntimeContext, ToolRuntimeServices
from src.policies.service import PolicyService, TurnClassification
from src.routing.service import RoutingInput, normalize_routing_input
from src.sandbox.service import SandboxService
from src.security.signing import SigningService
from src.sessions.repository import SessionRepository
from src.tools.registry import ToolRegistry
from src.tools.remote_exec import create_remote_exec_tool


def _create_session_and_message(session_manager):
    repository = SessionRepository()
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="web",
            channel_account_id="acct",
            sender_id="sender",
            peer_id="peer",
        )
    )
    with session_manager.session() as db:
        session = repository.get_or_create_session(db, routing)
        message = repository.append_message(
            db,
            session,
            role="user",
            content="run remote",
            external_message_id="m1",
            sender_id="sender",
            last_activity_at=datetime.now(timezone.utc),
        )
        db.commit()
        return session.id, message.id


def test_request_identity_and_signature_are_stable() -> None:
    first = derive_request_id(
        execution_run_id="run-1",
        tool_call_id="tool-1",
        execution_attempt_number=1,
    )
    second = derive_request_id(
        execution_run_id="run-1",
        tool_call_id="tool-1",
        execution_attempt_number=1,
    )
    later = derive_request_id(
        execution_run_id="run-1",
        tool_call_id="tool-1",
        execution_attempt_number=2,
    )
    assert first == second
    assert later != first

    signer = SigningService({"kid-1": "secret"})
    payload = {"request_id": first, "argv": ["/bin/echo", "hello"]}
    signature = signer.sign(key_id="kid-1", request_payload=payload)
    assert signer.verify(key_id="kid-1", request_payload=payload, signature=signature) is True
    assert signer.verify(
        key_id="kid-1",
        request_payload={"request_id": first, "argv": ["/bin/echo", "tampered"]},
        signature=signature,
    ) is False


def test_remote_exec_tool_binding_is_deny_by_default_and_exact_approval_only() -> None:
    registry = ToolRegistry(factories={"remote_exec": create_remote_exec_tool})
    args = {"text": "hello"}
    policy = PolicyService(remote_execution_enabled=True)
    approval_hash = policy.approval_lookup_key(capability_name="remote_exec", arguments=args)[1]
    approved_context = ToolRuntimeContext(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="sender-1",
        policy_context={
            "classification": TurnClassification(
                request_class="execute_action",
                capability_name="remote_exec",
                typed_action_id="tool.remote_exec",
                arguments=args,
            ),
            "approval_map": {
                ("remote_exec", "tool.remote_exec", approval_hash): {
                    "proposal_id": "proposal-1",
                    "resource_version_id": "version-1",
                    "content_hash": "content-1",
                    "typed_action_id": "tool.remote_exec",
                    "canonical_params_json": '{"text":"hello"}',
                    "canonical_params_hash": approval_hash,
                    "approval_id": "approval-1",
                    "active_resource_id": "active-1",
                }
            },
        },
        runtime_services=ToolRuntimeServices(),
    )
    denied_context = ToolRuntimeContext(
        session_id="session-1",
        message_id=1,
        agent_id="agent-1",
        channel_kind="web",
        sender_id="sender-1",
        policy_context={
            "classification": TurnClassification(
                request_class="execute_action",
                capability_name="remote_exec",
                typed_action_id="tool.remote_exec",
                arguments=args,
            ),
            "approval_map": {},
        },
        runtime_services=ToolRuntimeServices(),
    )

    assert set(registry.bind_tools(context=denied_context, policy_service=PolicyService()).keys()) == set()
    assert "remote_exec" in registry.bind_tools(context=approved_context, policy_service=policy)


def test_node_runner_executes_signed_request_and_reuses_duplicate_result(session_manager, tmp_path) -> None:
    session_id, message_id = _create_session_and_message(session_manager)
    settings = Settings(
        database_url=str(session_manager.engine.url),
        node_runner_signing_key_id="kid-1",
        node_runner_signing_secret="secret",
        node_runner_allowed_executables="/bin/echo",
        sandbox_workspace_root=str(tmp_path / "sandboxes"),
    )
    node_app = create_node_runner_app(settings=settings, session_manager=session_manager)
    client = TestClient(node_app)
    capabilities_repository = CapabilitiesRepository()
    template = NodeCommandTemplate.from_payload(
        {
            "executable": "/bin/echo",
            "argv_template": ["{text}"],
            "env_allowlist": [],
            "working_dir": None,
            "workspace_binding_kind": "session",
            "fixed_workspace_key": None,
            "workspace_mount_mode": "read_write",
            "typed_action_id": "tool.remote_exec",
            "sandbox_profile_key": "default",
            "timeout_seconds": 5,
            "capability_name": "remote_exec",
        }
    )

    with session_manager.session() as db:
        capabilities_repository.upsert_agent_sandbox_profile(
            db,
            agent_id="agent-1",
            default_mode="agent",
            shared_profile_key="shared-default",
            allow_off_mode=False,
            max_timeout_seconds=5,
        )
        _, version, approval, _ = capabilities_repository.create_remote_exec_capability(
            db,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            requested_by="sender",
            approver_id="sender",
            template_payload=template.to_payload() | {"capability_name": "remote_exec"},
            invocation_arguments={"text": "hello sandbox"},
        )
        db.commit()

    with session_manager.session() as db:
        sandbox = SandboxService(settings=settings, capabilities_repository=capabilities_repository).resolve(
            db,
            agent_id="agent-1",
            session_id=session_id,
            template=template,
        )
        invocation = RemoteInvocation(arguments={"text": "hello sandbox"}, env={}, working_dir=None, timeout_seconds=5)
        request = build_exec_request(
            execution_run_id="run-1",
            tool_call_id="tool-1",
            execution_attempt_number=1,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            approval_id=approval.id,
            resource_version_id=version.id,
            resource_payload_hash=version.content_hash,
            invocation=invocation,
            argv=derive_argv(template=template, arguments={"text": "hello sandbox"}),
            sandbox_mode=sandbox.sandbox_mode,
            sandbox_key=sandbox.sandbox_key,
            workspace_root=sandbox.workspace_root,
            workspace_mount_mode=sandbox.workspace_mount_mode,
            typed_action_id="tool.remote_exec",
            ttl_seconds=30,
        )
        signed = SigningService({"kid-1": "secret"}).build_signed_request(
            key_id="kid-1",
            request_payload=request.to_payload(),
        )

    first = client.post("/internal/node/exec", json=signed.signed_payload())
    duplicate = client.post("/internal/node/exec", json=signed.signed_payload())
    fetched = client.get(f"/internal/node/exec/{request.request_id}")

    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["stdout_preview"].strip() == "hello sandbox"
    assert duplicate.status_code == 200
    assert duplicate.json()["request_id"] == request.request_id
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "completed"


def test_remote_execution_runtime_dispatches_one_signed_request(session_manager, tmp_path) -> None:
    session_id, message_id = _create_session_and_message(session_manager)
    settings = Settings(
        database_url=str(session_manager.engine.url),
        remote_execution_enabled=True,
        node_runner_signing_key_id="kid-1",
        node_runner_signing_secret="secret",
        node_runner_allowed_executables="/bin/echo",
        sandbox_workspace_root=str(tmp_path / "sandboxes"),
    )
    capabilities_repository = CapabilitiesRepository()
    policy = PolicyService(remote_execution_enabled=True)
    captured: list[str] = []
    template = NodeCommandTemplate.from_payload(
        {
            "executable": "/bin/echo",
            "argv_template": ["{text}"],
            "env_allowlist": [],
            "working_dir": None,
            "workspace_binding_kind": "session",
            "fixed_workspace_key": None,
            "workspace_mount_mode": "read_write",
            "typed_action_id": "tool.remote_exec",
            "sandbox_profile_key": "default",
            "timeout_seconds": 5,
            "capability_name": "remote_exec",
        }
    )

    with session_manager.session() as db:
        capabilities_repository.upsert_agent_sandbox_profile(
            db,
            agent_id="agent-1",
            default_mode="agent",
            shared_profile_key="shared-default",
            allow_off_mode=False,
            max_timeout_seconds=5,
        )
        _, version, approval, active = capabilities_repository.create_remote_exec_capability(
            db,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            requested_by="sender",
            approver_id="sender",
            template_payload=template.to_payload() | {"capability_name": "remote_exec"},
            invocation_arguments={"text": "runtime hello"},
        )
        approval_match = policy.get_matching_approval(
            context=ToolRuntimeContext(
                session_id=session_id,
                message_id=message_id,
                agent_id="agent-1",
                channel_kind="web",
                sender_id="sender",
                policy_context={
                    "classification": TurnClassification(
                        request_class="execute_action",
                        capability_name="remote_exec",
                        typed_action_id="tool.remote_exec",
                        arguments={"text": "runtime hello"},
                    ),
                    "approval_map": {
                        ("remote_exec", "tool.remote_exec", approval.canonical_params_hash): {
                            "proposal_id": approval.proposal_id,
                            "resource_version_id": version.id,
                            "content_hash": version.content_hash,
                            "typed_action_id": approval.typed_action_id,
                            "canonical_params_json": approval.canonical_params_json,
                            "canonical_params_hash": approval.canonical_params_hash,
                            "approval_id": approval.id,
                            "active_resource_id": active.id,
                        }
                    },
                },
                runtime_services=ToolRuntimeServices(),
            ),
            capability_name="remote_exec",
            arguments={"text": "runtime hello"},
        )

        runtime = RemoteExecutionRuntime(
            settings=settings,
            capabilities_repository=capabilities_repository,
            sandbox_service=SandboxService(settings=settings, capabilities_repository=capabilities_repository),
            signing_service=SigningService({"kid-1": "secret"}),
            runner_client=lambda _db, signed_request: (
                captured.append(signed_request.request.request_id)
                or NodeExecutionResult(
                    request_id=signed_request.request.request_id,
                    status="completed",
                    exit_code=0,
                    stdout_preview="runtime hello\n",
                    stderr_preview="",
                    stdout_truncated=False,
                    stderr_truncated=False,
                )
            ),
        )
        result = runtime.execute(
            db,
            approval=approval_match,
            session_id=session_id,
            message_id=message_id,
            agent_id="agent-1",
            execution_run_id="run-1",
            tool_call_id="tool-1",
            execution_attempt_number=1,
            arguments={"text": "runtime hello"},
        )
        db.commit()

    assert result.status == "completed"
    assert len(captured) == 1
