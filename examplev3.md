# Example: Local Deployment Orchestration With Webchat, MailDev, Code Generation, and a Local Webhook Receiver

This guide gives you a fully local `python-claw` example you can run on one machine with no public webhooks and no external channel accounts. The only third-party credential you need is an OpenAI API key.

It showcases:

- gateway-first inbound routing and durable sessions
- async worker-owned execution runs
- provider-backed assistant turns
- durable sub-agent delegation
- remote execution through the node-runner
- code generation and execution in an isolated workspace
- callback-driven workflow continuation
- production auth, diagnostics, and quota posture

## Important Truth First

This version is intentionally aligned with the codebase as it exists today.

- User-facing traffic goes through the real `webchat` adapter and the real gateway.
- Delegations are created through the real `DelegationService`.
- Remote execution uses the real approval records, sandbox resolution, node-runner policy, and node-runner executor.
- The deployment callback still re-enters through the gateway as a new inbound event.

But this demo does **not** rely on the LLM to autonomously choose `delegate_to_agent` or `remote_exec` from ordinary chat turns.

That is the key design choice in this updated guide. The current repo supports delegation and remote execution, but it does not yet provide a deterministic end-user prompt path for those actions. So this demo uses two local helper scripts to make the specialist flow reproducible:

1. one helper creates the child delegations
2. one helper seeds the exact approved `remote_exec` action for each child session and executes it

That keeps the example honest and repeatable while still using the current `python-claw` code structure.

## Scenario

1. A user sends a deployment request through the built-in webchat adapter.
2. A helper command creates a real child delegation from `default-agent` to `deploy-agent`.
3. `deploy-agent` sends a deployment-start event to a local webhook receiver through approved `remote_exec`.
4. The deployment system sends a callback back into the **same parent session** through the gateway.
5. The user asks for a deployment report.
6. A helper command creates a real child delegation from `default-agent` to `code-agent`.
7. `code-agent` runs approved Python to generate `deploy_report.py` and `deploy_report.json` in its isolated workspace.
8. The user asks for an email notification.
9. A helper command creates a real child delegation from `default-agent` to `notify-agent`.
10. `notify-agent` runs approved Python with `smtplib` to send email through MailDev.

## Architecture

```text
User (curl)
    |
    v
[Webchat Adapter] --> [Gateway API :8000] --> [PostgreSQL]
                            |
                            v
                       [Worker]
                            |
                +-----------+-----------+
                |           |           |
         [deploy-agent] [code-agent] [notify-agent]
                |           |           |
         remote_exec   remote_exec   remote_exec
          (curl)       (python3)      (python3)
                |           |           |
                v           v           v
    [Webhook Receiver] [Session Workspace] [MailDev]
       localhost:3001   .claw-sandboxes    SMTP 1025 / Web 1080

Operator helper scripts:
- create-delegation.py
- run-approved-child-action.py
```

## Why This Version Works Better

- No Telegram bot setup
- No Slack app setup
- No Gmail bridge
- No public internet exposure
- No reliance on webhook.site
- No dependence on the LLM to plan exact `remote_exec` payloads correctly

## Prerequisites

- Python 3.11+
- `uv`
- Docker and Docker Compose
- Node.js 18+ and `npm`
- OpenAI API key

## Step 1: Install The Local Tools

Install MailDev:

```bash
npm install -g maildev
maildev --version
```

## Step 2: Create The Local Helper Files

### 2.1 Create `webhook-receiver.js`

Create [webhook-receiver.js](/Users/scottcornell/src/my-projects/python-claw/webhook-receiver.js) in the repo root:

```javascript
const http = require("http");

const PORT = 3001;
let requestCount = 0;

const server = http.createServer((req, res) => {
  if (req.method === "POST") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      requestCount++;
      const timestamp = new Date().toISOString();
      console.log(`\n--- Webhook #${requestCount} received at ${timestamp} ---`);
      console.log(`Path: ${req.url}`);
      console.log(`Body: ${body}`);
      console.log("---");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, received: requestCount }));
    });
  } else {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "webhook receiver running", received: requestCount }));
  }
});

server.listen(PORT, () => {
  console.log(`Webhook receiver listening on http://localhost:${PORT}`);
});
```

### 2.2 Create `create-delegation.py`

Create [create-delegation.py](/Users/scottcornell/src/my-projects/python-claw/create-delegation.py) in the repo root:

```python
from __future__ import annotations

import argparse

from apps.gateway.deps import create_delegation_service
from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager
from src.policies.service import PolicyService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-session-id", required=True)
    parser.add_argument("--parent-message-id", required=True, type=int)
    parser.add_argument("--parent-run-id", required=True)
    parser.add_argument("--child-agent-id", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--delegation-kind", required=True)
    parser.add_argument("--task-text", required=True)
    parser.add_argument("--expected-output", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    settings = get_settings()
    session_manager = DatabaseSessionManager(settings.database_url)
    service = create_delegation_service(settings)

    with session_manager.session() as db:
        result = service.create_delegation(
            db,
            policy_service=PolicyService(
                allowed_capabilities={"echo_text", "delegate_to_agent"},
                delegation_enabled=True,
                max_delegation_depth=2,
                allowed_child_agent_ids={"deploy-agent", "code-agent", "notify-agent"},
                max_active_delegations_per_run=1,
                max_active_delegations_per_session=3,
            ),
            parent_session_id=args.parent_session_id,
            parent_message_id=args.parent_message_id,
            parent_run_id=args.parent_run_id,
            parent_agent_id="default-agent",
            parent_policy_profile_key="default",
            parent_tool_profile_key="default",
            correlation_id=args.correlation_id,
            child_agent_id=args.child_agent_id,
            task_text=args.task_text,
            delegation_kind=args.delegation_kind,
            expected_output=args.expected_output or None,
            notes=args.notes or None,
        )
        record = service.repository.get_delegation(db, delegation_id=result.delegation_id)
        db.commit()

    print("delegation_id=", result.delegation_id)
    print("child_session_id=", result.child_session_id)
    print("child_message_id=", record.child_message_id)
    print("child_run_id=", result.child_run_id)


if __name__ == "__main__":
    main()
```

### 2.3 Create `run-approved-child-action.py`

Create [run-approved-child-action.py](/Users/scottcornell/src/my-projects/python-claw/run-approved-child-action.py) in the repo root:

```python
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from apps.gateway.deps import create_delegation_service
from apps.node_runner.executor import NodeRunnerExecutor
from apps.node_runner.policy import NodeRunnerPolicy
from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager
from src.execution.audit import ExecutionAuditRepository
from src.execution.contracts import (
    NodeCommandTemplate,
    NodeExecutionResult,
    RemoteInvocation,
    build_exec_request,
    derive_argv,
)
from src.jobs.repository import JobsRepository
from src.sandbox.service import SandboxService
from src.security.signing import SigningService
from src.sessions.repository import SessionRepository


def build_action(action: str) -> tuple[dict, dict, str]:
    if action == "deploy-webhook":
        payload = json.dumps(
            {
                "correlation_id": "northwind-api-staging-001",
                "event": "deployment_started",
                "app": "northwind-api",
                "environment": "staging",
            },
            separators=(",", ":"),
        )
        return (
            {
                "capability_name": "remote_exec",
                "executable": "/usr/bin/curl",
                "argv_template": [
                    "-X",
                    "POST",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    "{payload}",
                    "http://localhost:3001/deploy-events",
                ],
                "env_allowlist": [],
                "working_dir": None,
                "workspace_binding_kind": "session",
                "fixed_workspace_key": None,
                "workspace_mount_mode": "read_write",
                "typed_action_id": "tool.remote_exec",
                "sandbox_profile_key": "default",
                "timeout_seconds": 10,
            },
            {"payload": payload},
            "Deployment start webhook sent for northwind-api staging.",
        )

    if action == "generate-report":
        code = """import json, datetime, pathlib
report = {
    "app": "northwind-api",
    "environment": "staging",
    "status": "completed",
    "correlation_id": "northwind-api-staging-001",
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z"
}
pathlib.Path("deploy_report.json").write_text(json.dumps(report, indent=2))
script = '''import json, pathlib
report = json.loads(pathlib.Path("deploy_report.json").read_text())
print("=== Deployment Report ===")
for k, v in report.items():
    print(f"  {k}: {v}")
print("=========================")
'''
pathlib.Path("deploy_report.py").write_text(script)
exec(script)
"""
        return (
            {
                "capability_name": "remote_exec",
                "executable": "/usr/bin/python3",
                "argv_template": ["-c", "{code}"],
                "env_allowlist": [],
                "working_dir": None,
                "workspace_binding_kind": "session",
                "fixed_workspace_key": None,
                "workspace_mount_mode": "read_write",
                "typed_action_id": "tool.remote_exec",
                "sandbox_profile_key": "default",
                "timeout_seconds": 15,
            },
            {"code": code},
            "Generated deploy_report.py and deploy_report.json in the child workspace.",
        )

    if action == "send-maildev-email":
        code = """import smtplib
from email.message import EmailMessage
msg = EmailMessage()
msg["From"] = "python-claw@localhost"
msg["To"] = "ops-team@localhost"
msg["Subject"] = "Deployment complete northwind-api staging"
msg.set_content(
    "The deployment for northwind-api completed successfully.\\n"
    "Correlation id: northwind-api-staging-001\\n"
)
with smtplib.SMTP("localhost", 1025) as smtp:
    smtp.send_message(msg)
print("MailDev message sent")
"""
        return (
            {
                "capability_name": "remote_exec",
                "executable": "/usr/bin/python3",
                "argv_template": ["-c", "{code}"],
                "env_allowlist": [],
                "working_dir": None,
                "workspace_binding_kind": "session",
                "fixed_workspace_key": None,
                "workspace_mount_mode": "read_write",
                "typed_action_id": "tool.remote_exec",
                "sandbox_profile_key": "default",
                "timeout_seconds": 15,
            },
            {"code": code},
            "Sent deployment-complete email through MailDev.",
        )

    raise ValueError(f"unsupported action: {action}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["deploy-webhook", "generate-report", "send-maildev-email"])
    parser.add_argument("--child-agent-id", required=True)
    parser.add_argument("--child-session-id", required=True)
    parser.add_argument("--child-message-id", required=True, type=int)
    parser.add_argument("--child-run-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    session_manager = DatabaseSessionManager(settings.database_url)
    cap_repo = CapabilitiesRepository()
    audit_repo = ExecutionAuditRepository()
    jobs_repo = JobsRepository()
    session_repo = SessionRepository()
    delegation_service = create_delegation_service(settings)
    signing = SigningService({settings.node_runner_signing_key_id: settings.node_runner_signing_secret})

    template_payload, invocation_arguments, assistant_summary = build_action(args.action)

    with session_manager.session() as db:
        cap_repo.upsert_agent_sandbox_profile(
            db,
            agent_id=args.child_agent_id,
            default_mode="agent",
            shared_profile_key="shared-default",
            allow_off_mode=False,
            max_timeout_seconds=template_payload["timeout_seconds"],
        )
        _, version, approval, _ = cap_repo.create_remote_exec_capability(
            db,
            session_id=args.child_session_id,
            message_id=args.child_message_id,
            agent_id=args.child_agent_id,
            requested_by="demo-operator",
            approver_id="demo-operator",
            template_payload=template_payload,
            invocation_arguments=invocation_arguments,
        )

        template = NodeCommandTemplate.from_payload(template_payload)
        sandbox_service = SandboxService(settings=settings, capabilities_repository=cap_repo)
        sandbox = sandbox_service.resolve(
            db,
            agent_id=args.child_agent_id,
            session_id=args.child_session_id,
            template=template,
        )
        invocation = RemoteInvocation(
            arguments=invocation_arguments,
            env={},
            working_dir=None,
            timeout_seconds=template_payload["timeout_seconds"],
        )
        request = build_exec_request(
            execution_run_id=args.child_run_id,
            tool_call_id=f"{args.action}-1",
            execution_attempt_number=1,
            session_id=args.child_session_id,
            message_id=args.child_message_id,
            agent_id=args.child_agent_id,
            approval_id=approval.id,
            resource_version_id=version.id,
            resource_payload_hash=version.content_hash,
            invocation=invocation,
            argv=derive_argv(template=template, arguments=invocation_arguments),
            sandbox_mode=sandbox.sandbox_mode,
            sandbox_key=sandbox.sandbox_key,
            workspace_root=sandbox.workspace_root,
            workspace_mount_mode=sandbox.workspace_mount_mode,
            typed_action_id="tool.remote_exec",
            ttl_seconds=30,
        )
        signed = signing.build_signed_request(
            key_id=settings.node_runner_signing_key_id,
            request_payload=request.to_payload(),
        )

        policy = NodeRunnerPolicy(
            settings=settings,
            signing_service=signing,
            capabilities_repository=cap_repo,
            sandbox_service=sandbox_service,
            audit_repository=audit_repo,
        )
        executor = NodeRunnerExecutor(audit_repository=audit_repo)
        decision = policy.authorize(db, signed_request=signed)
        if decision.should_execute:
            result = executor.execute(db, record=decision.record, request=signed.request)
        else:
            record = audit_repo.get_by_request_id(db, request_id=request.request_id)
            result = NodeExecutionResult(
                request_id=record.request_id,
                status=record.status,
                exit_code=record.exit_code,
                stdout_preview=record.stdout_preview,
                stderr_preview=record.stderr_preview,
                stdout_truncated=record.stdout_truncated,
                stderr_truncated=record.stderr_truncated,
                deny_reason=record.deny_reason,
            )

        jobs_repo.mark_running(db, run_id=args.child_run_id, worker_id="demo-helper")
        child_session = session_repo.get_session(db, args.child_session_id)
        child_text = assistant_summary
        if result.stdout_preview.strip():
            child_text += f"\\n\\nstdout:\\n{result.stdout_preview.strip()}"
        session_repo.append_message(
            db,
            child_session,
            role="assistant",
            content=child_text,
            external_message_id=None,
            sender_id=args.child_agent_id,
            last_activity_at=datetime.now(timezone.utc),
        )
        jobs_repo.complete_run(db, run_id=args.child_run_id, worker_id="demo-helper")
        payload = delegation_service.handle_child_run_completed(db, child_run_id=args.child_run_id)
        db.commit()

    print("request_id=", result.request_id)
    print("status=", result.status)
    print("child_stdout=", result.stdout_preview.strip())
    print("delegation_result_payload=", payload.model_dump_json() if payload else None)


if __name__ == "__main__":
    main()
```

## Step 3: Start Local Infrastructure

Start PostgreSQL and Redis:

```bash
docker compose --env-file .env up -d
docker compose ps
```

Start MailDev in a second terminal:

```bash
maildev --smtp 1025 --web 1080
```

Open `http://localhost:1080`.

Start the webhook receiver in a third terminal:

```bash
node webhook-receiver.js
curl http://localhost:3001
```

## Step 4: Configure `.env`

Start from the example:

```bash
cp .env.example .env
```

Use this local configuration:

```text
PYTHON_CLAW_APP_NAME=python-claw-gateway

PYTHON_CLAW_POSTGRES_DB=openassistant
PYTHON_CLAW_POSTGRES_USER=openassistant
PYTHON_CLAW_POSTGRES_PASSWORD=openassistant
PYTHON_CLAW_POSTGRES_PORT=5432
PYTHON_CLAW_REDIS_PORT=6379

PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant

PYTHON_CLAW_DEFAULT_AGENT_ID=default-agent

PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=YOUR_OPENAI_API_KEY
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=700
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
PYTHON_CLAW_LLM_DISABLE_TOOLS=false

PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true
PYTHON_CLAW_NODE_RUNNER_MODE=in_process
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=local-demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=local-demo-signing-secret
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env,/usr/bin/python3
PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE=false

PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true
PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=demo-operator-token
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=demo-internal-token
PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id
PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=demo-operator-token
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=demo-internal-token

PYTHON_CLAW_RATE_LIMITS_ENABLED=true
PYTHON_CLAW_INBOUND_REQUESTS_PER_MINUTE_PER_CHANNEL_ACCOUNT=20
PYTHON_CLAW_ADMIN_REQUESTS_PER_MINUTE_PER_OPERATOR=30
PYTHON_CLAW_APPROVAL_ACTION_REQUESTS_PER_MINUTE_PER_SESSION=20
PYTHON_CLAW_PROVIDER_TOKENS_PER_HOUR_PER_AGENT=200000
PYTHON_CLAW_PROVIDER_REQUESTS_PER_MINUTE_PER_MODEL=120
PYTHON_CLAW_QUOTA_COUNTER_RETENTION_DAYS=7

PYTHON_CLAW_DELEGATION_PACKAGE_TRANSCRIPT_TURNS=6
PYTHON_CLAW_DELEGATION_PACKAGE_RETRIEVAL_ITEMS=4
PYTHON_CLAW_DELEGATION_PACKAGE_ATTACHMENT_ITEMS=2
PYTHON_CLAW_DELEGATION_PACKAGE_MAX_CHARS=4000

PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":true,"max_delegation_depth":2,"allowed_child_agent_ids":["deploy-agent","code-agent","notify-agent"],"max_active_delegations_per_run":1,"max_active_delegations_per_session":3},{"key":"deploy-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null},{"key":"code-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null},{"key":"notify-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null}]

PYTHON_CLAW_TOOL_PROFILES=[{"key":"default","allowed_capability_names":["echo_text","delegate_to_agent"]},{"key":"deploy-tools","allowed_capability_names":["echo_text","remote_exec"]},{"key":"code-tools","allowed_capability_names":["echo_text","remote_exec"]},{"key":"notify-tools","allowed_capability_names":["echo_text","remote_exec"]}]

PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[{"agent_id":"deploy-agent","model_profile_key":"default","policy_profile_key":"deploy-policy","tool_profile_key":"deploy-tools"},{"agent_id":"code-agent","model_profile_key":"default","policy_profile_key":"code-policy","tool_profile_key":"code-tools"},{"agent_id":"notify-agent","model_profile_key":"default","policy_profile_key":"notify-policy","tool_profile_key":"notify-tools"}]

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"}]
```

## Step 5: Install Dependencies, Run Migrations, and Start The Gateway

```bash
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn apps.gateway.main:app --reload --host 0.0.0.0 --port 8000
```

Verify health:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready -H 'Authorization: Bearer demo-operator-token'
```

## Step 6: Send The Initial Deployment Request Through Webchat

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "message_id": "msg-001",
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Deploy the fake app northwind-api to staging. Use correlation id northwind-api-staging-001."
  }'
```

Write down from the response:

- `SESSION_ID`
- `MESSAGE_ID`
- `PARENT_RUN_ID`

Optional: run the worker until idle for the parent's normal assistant response.

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

## Step 7: Create The `deploy-agent` Delegation

```bash
uv run python create-delegation.py \
  --parent-session-id "$SESSION_ID" \
  --parent-message-id "$MESSAGE_ID" \
  --parent-run-id "$PARENT_RUN_ID" \
  --child-agent-id deploy-agent \
  --correlation-id example2-deploy-001 \
  --delegation-kind deployment_start \
  --task-text "Trigger the local deployment-start webhook for northwind-api staging." \
  --expected-output "A short confirmation that the deployment-start event was posted."
```

Write down:

- `DEPLOY_CHILD_SESSION_ID`
- `DEPLOY_CHILD_MESSAGE_ID`
- `DEPLOY_CHILD_RUN_ID`

## Step 8: Run The `deploy-agent` Child Action

```bash
uv run python run-approved-child-action.py \
  --action deploy-webhook \
  --child-agent-id deploy-agent \
  --child-session-id "replace-with-deploy-child-session-id" \
  --child-message-id "replace-with-deploy-child-message-id" \
  --child-run-id "replace-with-deploy-child-run-id"
```

Then process the queued parent continuation run:

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

Verify the webhook receiver terminal shows the POST.

## Step 9: Send The Deployment Callback Back Into The Same Parent Session

This callback must use the **same routing tuple** as the original direct session. That means:

- `channel_kind=webchat`
- `channel_account_id=webchat-demo`
- `peer_id=demo-user`

Run:

```bash
curl -X POST http://localhost:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "webchat-demo",
    "external_message_id": "deploy-callback-001",
    "sender_id": "deployment-system",
    "peer_id": "demo-user",
    "content": "deployment_callback status=completed app=northwind-api environment=staging correlation_id=northwind-api-staging-001"
  }'
```

## Step 10: Ask For The Deploy Report

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "message_id": "msg-002",
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Create a deploy report for the completed northwind-api staging deployment."
  }'
```

Write down:

- `CODE_MESSAGE_ID`
- `CODE_PARENT_RUN_ID`

## Step 11: Create The `code-agent` Delegation

```bash
uv run python create-delegation.py \
  --parent-session-id "$SESSION_ID" \
  --parent-message-id "$CODE_MESSAGE_ID" \
  --parent-run-id "$CODE_PARENT_RUN_ID" \
  --child-agent-id code-agent \
  --correlation-id example2-code-001 \
  --delegation-kind generate_report \
  --task-text "Generate and execute a Python deploy report script for northwind-api staging." \
  --expected-output "A short summary of the generated report files and script output."
```

Write down:

- `CODE_CHILD_SESSION_ID`
- `CODE_CHILD_MESSAGE_ID`
- `CODE_CHILD_RUN_ID`

## Step 12: Run The `code-agent` Child Action

```bash
uv run python run-approved-child-action.py \
  --action generate-report \
  --child-agent-id code-agent \
  --child-session-id "replace-with-code-child-session-id" \
  --child-message-id "replace-with-code-child-message-id" \
  --child-run-id "replace-with-code-child-run-id"
```

Then process the queued parent continuation run:

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

Verify the generated files:

```bash
find .claw-sandboxes/sessions/code-agent/ -type f
cat .claw-sandboxes/sessions/code-agent/*/deploy_report.json
cat .claw-sandboxes/sessions/code-agent/*/deploy_report.py
```

## Step 13: Ask For The MailDev Notification

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "message_id": "msg-003",
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Send a deployment-complete notification email through MailDev."
  }'
```

Write down:

- `NOTIFY_MESSAGE_ID`
- `NOTIFY_PARENT_RUN_ID`

## Step 14: Create The `notify-agent` Delegation

```bash
uv run python create-delegation.py \
  --parent-session-id "$SESSION_ID" \
  --parent-message-id "$NOTIFY_MESSAGE_ID" \
  --parent-run-id "$NOTIFY_PARENT_RUN_ID" \
  --child-agent-id notify-agent \
  --correlation-id example2-notify-001 \
  --delegation-kind send_notification \
  --task-text "Send a deployment-complete email through MailDev for northwind-api staging." \
  --expected-output "A short confirmation that the email was sent."
```

Write down:

- `NOTIFY_CHILD_SESSION_ID`
- `NOTIFY_CHILD_MESSAGE_ID`
- `NOTIFY_CHILD_RUN_ID`

## Step 15: Run The `notify-agent` Child Action

```bash
uv run python run-approved-child-action.py \
  --action send-maildev-email \
  --child-agent-id notify-agent \
  --child-session-id "replace-with-notify-child-session-id" \
  --child-message-id "replace-with-notify-child-message-id" \
  --child-run-id "replace-with-notify-child-run-id"
```

Then process the queued parent continuation run:

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

Open MailDev at `http://localhost:1080` and verify the message arrived.

## Step 16: Inspect The Durable Record

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'

curl -s "$BASE/sessions/$SESSION_ID" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/$SESSION_ID/messages" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/$SESSION_ID/runs" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/$SESSION_ID/delegations" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool
```

Poll webchat deliveries:

```bash
curl -s "http://localhost:8000/providers/webchat/accounts/webchat-demo/poll?stream_id=demo-user&limit=50" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | python3 -m json.tool
```

## What This Demo Proves

| Capability | How it is demonstrated |
|-----------|------------------------|
| Gateway-first routing | User traffic enters through `/providers/webchat/.../messages`; callback enters through `/inbound/message` |
| Durable session continuity | The same session persists across user messages, callback re-entry, and delegation results |
| Real sub-agent structure | Child sessions and child runs are created through `DelegationService` |
| Real remote execution structure | Approved `remote_exec` actions go through resource approval records, sandbox resolution, node-runner policy, and executor |
| Workspace isolation | `code-agent` writes files into its per-session workspace under `.claw-sandboxes/sessions/code-agent/...` |
| Callback re-entry | The callback resumes the same parent session because it uses the same routing tuple |
| Local observability | Webhook receiver stdout, MailDev UI, workspace files, session APIs, and node-execution diagnostics all show the flow |

## Troubleshooting

### Webchat request returns 422

Use the real webchat payload shape:

- `actor_id`
- `content`
- optional `message_id`
- `peer_id`

Do not send `sender_id` or `external_message_id` to the webchat route.

### The callback created a new session

Your callback routing tuple did not match the original session. Use:

- `channel_kind=webchat`
- `channel_account_id=webchat-demo`
- `peer_id=demo-user`

### No files appear in `.claw-sandboxes`

Check:

```bash
curl -s http://localhost:8000/diagnostics/node-executions \
  -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
which python3
```

If `python3` is not `/usr/bin/python3`, update `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES` and the helper script accordingly.

### MailDev shows no email

Verify local SMTP first:

```bash
python3 - <<'PY'
import smtplib
from email.message import EmailMessage
msg = EmailMessage()
msg["From"] = "test@localhost"
msg["To"] = "test@localhost"
msg["Subject"] = "maildev test"
msg.set_content("hello")
with smtplib.SMTP("localhost", 1025) as smtp:
    smtp.send_message(msg)
print("sent")
PY
```

### The parent assistant did not autonomously delegate

That is expected in this guide. The example is intentionally operator-assisted for delegation and exact `remote_exec` approval so it stays deterministic on the current codebase.

## Cleanup

```bash
# Stop MailDev, webhook receiver, and gateway with Ctrl+C in their terminals
docker compose --env-file .env down
rm -rf .claw-sandboxes/
docker compose --env-file .env down -v
```

## Final Note

This is the best-fit local example for `python-claw` right now if you want something reproducible and honest about the current architecture. It proves the real session, delegation, callback, approval, sandbox, and node-runner seams without pretending the current prompt flow is already a fully autonomous multi-agent deployment orchestrator.
