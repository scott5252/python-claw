# Demo Guide

This guide shows a junior technical person how to:

1. Set up the application
2. Run the application
3. Demonstrate a complete, successful chat flow from start to finish
4. Exercise the remote execution feature accurately

The demo uses a real-world scenario:

- a bicycle repair shop employee wants the system to send a pickup-ready message to a customer

This is a good demo because it shows the main parts of the current system:

- gateway-owned inbound message handling
- durable session creation and transcript persistence
- queued async execution
- approval-gated action handling
- assistant response persistence
- outbound delivery auditing
- separate node-runner execution contracts

Important note about the current implementation:

- the default assistant is rule-based, not an LLM
- a normal message returns `Received: <your text>`
- a message that starts with `send ` triggers the approval workflow for `send_message`
- after approval, sending the same `send ...` command again succeeds and creates a durable outbound delivery record
- the current workspace does not expose a normal end-user chat prompt that asks for `remote_exec`
- remote execution is implemented, but it is best demonstrated here as an operator/internal-service exercise rather than pretending a normal user can trigger it from chat today

## 1. What You Will Run

For a successful local demo, you will run:

- PostgreSQL and Redis with Docker Compose
- database migrations
- the gateway API
- the local one-pass worker helper
- optionally, the node runner for the remote execution exercise

You do not need the node runner for the main chat demo.
You do need it for the remote execution section later in this document.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime

You should work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Setup The Application

### Step 1: Prepare the environment file

If `.env` does not already exist, create it from `.env.example`:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_REMOTE_EXECUTION_ENABLED=true
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=demo-secret
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/bin/echo
```

What is happening in the system:

- the app loads configuration from `.env`
- the database URL tells the gateway and worker where PostgreSQL lives
- the diagnostics token protects `/health/ready` and `/diagnostics/*`
- remote execution is enabled so the later advanced exercise can run
- the signing key and secret give the gateway-side runtime and node runner a shared request-signing identity
- the allowlist is intentionally narrow so the remote execution demo stays safe and predictable

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What is happening in the system:

- `uv` creates or updates the local virtual environment
- Python packages needed by the gateway, worker, SQLAlchemy, FastAPI, Alembic, and tests are installed

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
```

What is happening in the system:

- PostgreSQL starts and becomes the durable store for sessions, messages, runs, approvals, and diagnostics
- Redis also starts because it is part of the local development stack, even though this specific demo path does not depend on it

### Step 4: Apply the database schema

Run:

```bash
uv run alembic upgrade head
```

What is happening in the system:

- Alembic creates all current tables from Specs 001 through 008
- after this step, the gateway can persist inbound messages and the worker can process queued runs

## 4. Run The Application

Use three terminals for the main demo. Use a fourth terminal later if you also run the node runner section.

### Terminal A: Start the gateway API

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

What is happening in the system:

- FastAPI starts on `http://127.0.0.1:8000`
- the app creates shared services for sessions, execution runs, scheduler support, health, and diagnostics
- no user-visible work happens yet because no inbound message has been submitted

### Terminal B: Keep a worker terminal ready

You will run this command after each user message:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system when you run it:

- the helper opens a database session
- it claims at most one eligible `execution_runs` row
- it processes that one queued run
- it commits and exits

This project does not run a long-lived worker by default in the local demo flow. You trigger one worker pass manually each time.

### Terminal C: Use curl to simulate the user chat

Set these helpful variables:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
```

Verify the gateway is live:

```bash
curl $BASE/health/live
```

Expected result:

- HTTP 200
- JSON with `"status": "ok"`

Verify readiness:

```bash
curl $BASE/health/ready -H "$AUTH"
```

Equivalent one-line form:

```bash
curl $BASE/health/ready -H 'Authorization: Bearer change-me'
```

Expected result:

- HTTP 200
- a PostgreSQL check with status `ok`

What is happening in the system:

- `/health/live` only checks that the process is running
- `/health/ready` also checks that the app can talk to PostgreSQL

## Main Demo

This section is the primary end-to-end demo for most audiences. It shows a real user conversation, approval gating, worker execution, and outbound delivery.

### Scenario

A shop employee wants to notify customer Maya that bike repair order `BR-1042` is complete and ready for pickup.

We will demonstrate three turns:

1. The employee asks the system to send the pickup message.
2. The system requires approval and creates a proposal.
3. The employee approves the proposal.
4. The employee repeats the send request.
5. The system prepares the outbound message and records a successful delivery.

This is a real-world workflow because production systems often require approval before sending an external customer communication.

### Turn 1: Request The Outbound Customer Message

### Step 1: Submit the first inbound message

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo-msg-1",
    "sender_id": "employee-alex",
    "content": "send Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- JSON similar to:

```json
{
  "session_id": "....",
  "message_id": 1,
  "run_id": "....",
  "status": "queued",
  "dedupe_status": "accepted",
  "trace_id": "...."
}
```

Write down:

- `session_id`
- `run_id`
- `trace_id`

What is happening in the system:

1. The gateway validates the request.
2. It checks `inbound_dedupe` to make sure `demo-msg-1` has not already been processed.
3. It resolves or creates a direct-message session using:
   - `channel_kind=webchat`
   - `channel_account_id=bike-shop-demo`
   - `peer_id=customer-maya`
4. It appends the user message to `messages`.
5. It creates one queued `execution_runs` row.
6. It finalizes the dedupe record.
7. It returns quickly with `202 Accepted`.

At this point, the assistant has not replied yet. The work is only queued.

### Step 2: Process the queued run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- it prints the `run_id` that was processed

What is happening in the system:

1. The worker claims the queued run from `execution_runs`.
2. It acquires a session lane lease so no second worker can run the same conversation at the same time.
3. It assembles the turn context from the transcript.
4. The policy layer sees that the message begins with `send `.
5. `send_message` is approval-gated, and there is no active approval yet.
6. The graph creates:
   - a `resource_proposals` row
   - a `resource_versions` row
   - `governance_transcript_events` rows for proposal creation and approval requested
7. The graph appends an assistant message telling the user approval is required.
8. The worker writes a `context_manifests` row.
9. The worker marks the run `completed`.

### Step 3: Read the chat transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=10
```

Replace `<SESSION_ID>` with the `session_id` from the first response.

Expected result:

- two messages in order
- the first is the original user message
- the second is an assistant message similar to:

```text
Approval required for `send_message`. Proposal `<proposal_id>` is waiting for approval. Review packet: action `tool.send_message`, params `{"text":"Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM."}`. Reply `approve <proposal_id>` to activate it.
```

What is happening in the system:

- this endpoint reads durable transcript rows from `messages`
- the assistant reply you see was produced by the worker, not by the original HTTP request

### Step 4: Read the pending approval

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/governance/pending
```

Expected result:

- one pending approval item
- it contains:
  - `proposal_id`
  - `capability_name` equal to `send_message`
  - `typed_action_id` equal to `tool.send_message`
  - the canonical parameters for the message text

Write down the `proposal_id`.

What is happening in the system:

- the endpoint reads `resource_proposals` and `resource_versions`
- it returns the durable approval work queue for that session

### Turn 2: Approve The Proposed Customer Message

### Step 5: Submit the approval message

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo-msg-2",
    "sender_id": "employee-alex",
    "content": "approve <PROPOSAL_ID>",
    "peer_id": "customer-maya"
  }'
```

Replace `<PROPOSAL_ID>` with the value from the pending approval response.

Expected result:

- HTTP 202
- same `session_id` as before
- a new `message_id`
- a new `run_id`

What is happening in the system:

1. The gateway creates a second user message in the same session.
2. It creates another queued execution run.
3. Because `external_message_id` changed from `demo-msg-1` to `demo-msg-2`, this is treated as a new inbound message and not a duplicate.

### Step 6: Process the approval run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the new run.
2. The graph classifies the message as an approval decision.
3. It updates the proposal lifecycle by creating or updating:
   - `resource_approvals`
   - `active_resources`
   - `governance_transcript_events` for approval decision and activation result
4. It appends an assistant confirmation message to `messages`.
5. It writes a new `context_manifests` row.
6. It completes the run.

### Step 7: Read the transcript again

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=10
```

Expected result:

- you now see the approval command and a new assistant reply
- the newest assistant reply is similar to:

```text
Approved proposal `<proposal_id>` for `send_message`. Retry the original request to use the newly active capability.
```

What is happening in the system:

- the approval is now active for the exact `send_message` parameters that were approved
- the runtime will allow the same send command on the next turn

### Turn 3: Send The Approved Customer Message

### Step 8: Submit the same send request again

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo-msg-3",
    "sender_id": "employee-alex",
    "content": "send Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- same `session_id`
- a new queued `run_id`

What is happening in the system:

1. The gateway appends the third user message to the same session transcript.
2. It creates another queued run.
3. Because the approval is now active, this run will be allowed to prepare an outbound message.

### Step 9: Process the send run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the run.
2. The graph sees that `send_message` is now allowed for these exact parameters.
3. The `send_message` tool creates a runtime-owned outbound intent.
4. The graph appends:
   - tool proposal and tool result rows in `session_artifacts`
   - tool audit rows in `tool_audit_events`
   - an assistant message in `messages` with:
     - `Prepared outbound message: Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM.`
5. After the graph finishes, the worker calls the outbound dispatcher.
6. The dispatcher creates:
   - one `outbound_deliveries` row
   - one `outbound_delivery_attempts` row
7. The local `webchat` adapter returns a synthetic success result, so the delivery is marked `sent`.
8. The worker queues derived `outbox_jobs`.
9. The worker marks the run completed.

### Step 10: Read the final transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=20
```

Expected result:

- you should now see the full conversation:
  - original send request
  - approval-required assistant reply
  - approval command
  - approval-confirmed assistant reply
  - repeated send request
  - final assistant reply beginning with `Prepared outbound message:`

This is the end of the successful chat demo.

### Show The Main Chat Demo Evidence

These commands prove the internal workflow succeeded.

### Step 11: Show the session record

```bash
curl -s $BASE/sessions/<SESSION_ID>
```

What it proves:

- the direct chat has one durable `sessions` row

### Step 12: Show all runs for the session

```bash
curl -s $BASE/sessions/<SESSION_ID>/runs
```

Expected result:

- three runs for the three inbound messages
- each should have terminal status `completed`

What it proves:

- the gateway accepted three turns
- the worker processed them successfully from the durable queue

### Step 13: Show diagnostics for deliveries

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Expected result:

- at least one delivery item
- the delivery should have `status` equal to `sent`

What it proves:

- the approved send request became an outbound delivery
- the dispatcher and adapter path completed successfully

### Step 14: Show continuity diagnostics for the session

If you have not already done so, set a shell variable first:

```bash
SESSION_ID=<the session_id from the first inbound response>
```

```bash
curl -s $BASE/diagnostics/sessions/$SESSION_ID/continuity -H "$AUTH"
```

Expected result:

- `capability_status` is `enabled`
- `context_manifest_count` is at least `1`
- `recent_run_statuses` includes completed runs

What it proves:

- context assembly happened and was persisted
- the session has inspectable continuity state

Troubleshooting:

- if this returns `404 Not Found`, make sure you replaced the placeholder with a real session ID from the earlier inbound response
- if this and Step 15 both return `404 Not Found`, the process on `127.0.0.1:8000` is likely not the current gateway app, so restart Terminal A with `uv run uvicorn apps.gateway.main:app --reload`

### Step 15: Show overall run diagnostics

If you want one more operator-facing check, run:

```bash
curl -s $BASE/diagnostics/runs -H "$AUTH"
```

What it proves:

- the operator diagnostics layer is reading the same durable run records the worker updated

## Advanced Demo

This section is an operator-focused demo for the remote execution feature. It is accurate, but it is not a normal end-user chat flow in the current workspace.

### Remote Execution Feature

This section demonstrates the remote execution feature accurately.

Important truth first:

- the remote execution feature exists
- the separate node runner app exists at `apps.node_runner.main:app`
- but the current default chat prompt flow does not ask for `remote_exec`

That means this part of the demo is operator-driven, not ordinary end-user chat.

### What this exercise proves

This exercise proves that:

- an approved `node_command_template` can exist in the database
- sandbox resolution is deterministic
- a signed request can be sent to the separate node-runner service
- the node runner executes an allowlisted command
- `node_execution_audits` records the request and result durably

### Terminal D: Start the node runner

In a fourth terminal, run:

```bash
uv run uvicorn apps.node_runner.main:app --reload --port 8010
```

Verify it is live:

```bash
curl http://127.0.0.1:8010/health/live
```

Expected result:

- HTTP 200
- JSON with `"service": "python-claw-node-runner"`

What is happening in the system:

- the separate node-runner FastAPI app starts
- it loads the same database and signing settings
- it exposes the internal execution routes used for signed node-exec requests

### Step 16: Seed one approved remote execution capability

Run this command from the project root:

```bash
uv run python - <<'PY'
from datetime import datetime, timezone

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import get_settings
from src.db.base import Base
from src.db.session import DatabaseSessionManager
from src.jobs.repository import JobsRepository
from src.routing.service import RoutingInput, normalize_routing_input
from src.sessions.repository import SessionRepository

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
Base.metadata.create_all(manager.engine)

session_repo = SessionRepository()
cap_repo = CapabilitiesRepository()
jobs_repo = JobsRepository()

with manager.session() as db:
    routing = normalize_routing_input(
        RoutingInput(
            channel_kind="webchat",
            channel_account_id="remote-exec-demo",
            sender_id="operator-riley",
            peer_id="ops-peer-1",
        )
    )
    session = session_repo.get_or_create_session(db, routing)
    message = session_repo.append_message(
        db,
        session,
        role="user",
        content="remote exec demo seed",
        external_message_id="remote-exec-seed-1",
        sender_id="operator-riley",
        last_activity_at=datetime.now(timezone.utc),
    )
    cap_repo.upsert_agent_sandbox_profile(
        db,
        agent_id="default-agent",
        default_mode="agent",
        shared_profile_key="shared-default",
        allow_off_mode=False,
        max_timeout_seconds=5,
    )
    proposal, version, approval, active = cap_repo.create_remote_exec_capability(
        db,
        session_id=session.id,
        message_id=message.id,
        agent_id="default-agent",
        requested_by="operator-riley",
        approver_id="operator-riley",
        template_payload={
            "capability_name": "remote_exec",
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
        },
        invocation_arguments={"text": "hello from remote exec demo"},
    )
    run = jobs_repo.create_or_get_execution_run(
        db,
        session_id=session.id,
        message_id=message.id,
        agent_id="default-agent",
        trigger_kind="inbound_message",
        trigger_ref=str(message.id),
        lane_key=session.id,
        max_attempts=3,
    )
    db.commit()
    print("session_id=", session.id)
    print("message_id=", message.id)
    print("execution_run_id=", run.id)
    print("resource_version_id=", version.id)
    print("approval_id=", approval.id)
PY
```

Write down:

- `session_id`
- `message_id`
- `execution_run_id`
- `resource_version_id`
- `approval_id`

What is happening in the system:

1. A session and transcript message are created for traceability.
2. A queued `execution_runs` row is created so the node runner can persist an audit row that points at a real parent run.
3. A sandbox profile row is written to `agent_sandbox_profiles`.
4. A `node_command_template` resource is created and approved through:
   - `resource_proposals`
   - `resource_versions`
   - `resource_approvals`
   - `active_resources`
5. This approval is exact-match scoped to the parameter payload `{"text":"hello from remote exec demo"}`.

### Step 17: Send one valid signed request to the node runner

Run:

```bash
uv run python - <<'PY'
import json
import urllib.request

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import get_settings
from src.db.session import DatabaseSessionManager
from src.execution.contracts import NodeCommandTemplate, RemoteInvocation, build_exec_request, derive_argv
from src.sandbox.service import SandboxService
from src.security.signing import SigningService

settings = get_settings()
manager = DatabaseSessionManager(settings.database_url)
cap_repo = CapabilitiesRepository()

resource_version_id = "<RESOURCE_VERSION_ID>"
approval_id = "<APPROVAL_ID>"
session_id = "<SESSION_ID>"
message_id = <MESSAGE_ID>
execution_run_id = "<EXECUTION_RUN_ID>"
agent_id = "default-agent"

with manager.session() as db:
    version = cap_repo.get_resource_version(db, resource_version_id=resource_version_id)
    template = NodeCommandTemplate.from_payload(json.loads(version.resource_payload))
    sandbox = SandboxService(settings=settings, capabilities_repository=cap_repo).resolve(
        db,
        agent_id=agent_id,
        session_id=session_id,
        template=template,
    )
    invocation = RemoteInvocation(
        arguments={"text": "hello from remote exec demo"},
        env={},
        working_dir=None,
        timeout_seconds=5,
    )
    request = build_exec_request(
        execution_run_id=execution_run_id,
        tool_call_id="remote-demo-tool-1",
        execution_attempt_number=1,
        session_id=session_id,
        message_id=message_id,
        agent_id=agent_id,
        approval_id=approval_id,
        resource_version_id=version.id,
        resource_payload_hash=version.content_hash,
        invocation=invocation,
        argv=derive_argv(template=template, arguments={"text": "hello from remote exec demo"}),
        sandbox_mode=sandbox.sandbox_mode,
        sandbox_key=sandbox.sandbox_key,
        workspace_root=sandbox.workspace_root,
        workspace_mount_mode=sandbox.workspace_mount_mode,
        typed_action_id="tool.remote_exec",
        ttl_seconds=30,
    )
    signed = SigningService({settings.node_runner_signing_key_id: settings.node_runner_signing_secret}).build_signed_request(
        key_id=settings.node_runner_signing_key_id,
        request_payload=request.to_payload(),
    )

request = urllib.request.Request(
    "http://127.0.0.1:8010/internal/node/exec",
    data=json.dumps(signed.signed_payload()).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.status)
    print(json.loads(response.read().decode("utf-8")))
PY
```

Replace the placeholders with the values from Step 16.

Expected result:

- HTTP 200
- JSON with:
  - a stable `request_id`
  - `status` equal to `completed`
  - `stdout_preview` containing `hello from remote exec demo`

What is happening in the system:

1. The client builds a canonical `NodeExecRequest`.
2. The payload is signed with the configured signing key.
3. The node runner verifies the signature, TTL window, executable allowlist, and sandbox resolution.
4. It inserts or reuses a row in `node_execution_audits`.
5. It runs `/bin/echo`.
6. It records stdout, stderr, exit code, and terminal status in the audit row.

### Step 18: Replay the exact same signed request

Run the exact same script from Step 17 again.

Expected result:

- HTTP 200
- the same `request_id`
- the same persisted completed result

What is happening in the system:

- the node runner sees that the same logical execution attempt already has a durable audit row
- it returns the persisted state instead of starting a second process

### Step 19: Inspect remote execution diagnostics

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/node-executions -H "$AUTH"
```

Expected result:

- at least one item
- the newest item should show:
  - a `request_id`
  - `status` equal to `completed`
  - the resolved `sandbox_mode`

What it proves:

- the remote execution feature wrote durable operational state that the gateway diagnostics surface can read

## Not Covered

Even with the added node-runner section, this demo still does not cover every implemented feature.

Not fully demonstrated:

- attachment normalization with `inbound_message_attachments` and `message_attachments`
- media or voice outbound delivery
- reply directives
- group-chat session routing using `group_id`
- scheduler-created runs with `scheduled_jobs` and `scheduled_job_fires`
- duplicate inbound replay handling in the live demo
- retry, dead-letter, and stale-lease recovery paths
- degraded continuity and summary-repair paths
- a normal end-user chat prompt flow for remote execution

Why the last point matters:

- remote execution is implemented
- but the current default model adapter only understands plain text, `echo ...`, and `send ...`
- it does not generate a `remote_exec` tool request from a user chat message today

## Notes

This demo is reliable because it matches the current code exactly:

- `send ` triggers the approval-gated `send_message` path
- `approve <proposal_id>` activates the approval
- repeating the same `send ...` command succeeds because the approval is an exact parameter match
- `webchat` uses a thin local adapter that always returns a synthetic success result for text delivery
- the remote execution section uses the implemented signed-request and node-runner path directly, because the current default prompt flow does not yet ask for `remote_exec`

That means no external transport account or LLM key is required for a successful demo. The separate node runner is only required for the advanced remote execution section.

## Common Mistakes And Fixes

### Mistake: `/health/ready` returns 401

Cause:

- you did not send the admin bearer token

Fix:

```bash
curl $BASE/health/ready -H 'Authorization: Bearer change-me'
```

### Mistake: the assistant reply does not appear after posting to `/inbound/message`

Cause:

- the gateway only queues the work
- you did not run the worker helper

Fix:

Run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Mistake: a later message creates a different session

Cause:

- you changed the routing identity

For this direct-message demo, keep these values the same for every turn:

- `channel_kind`
- `channel_account_id`
- `peer_id`

Also keep using new `external_message_id` values each turn.

### Mistake: the final send still asks for approval

Cause:

- you did not repeat the exact same `send ...` text after approval

Fix:

- use exactly the same message content you approved
- the approval match is exact by canonical parameters

### Mistake: the remote execution script is rejected

Common causes:

- the gateway and node runner are using different signing keys or secrets
- `PYTHON_CLAW_REMOTE_EXECUTION_ENABLED` is not `true`
- the executable is not on the allowlist
- the placeholders in the script were not replaced correctly

Fix:

- verify `.env` values
- make sure `/bin/echo` is in `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES`
- restart the gateway and node runner after changing `.env`

## Quick Demo Checklist

```text
[ ] .env is present and includes diagnostics tokens
[ ] .env enables remote execution and allows /bin/echo
[ ] uv sync --group dev completed
[ ] docker compose --env-file .env up -d completed
[ ] uv run alembic upgrade head completed
[ ] gateway is running on http://127.0.0.1:8000
[ ] /health/live returns 200
[ ] /health/ready returns 200 with Authorization header
[ ] first send request returns 202
[ ] worker helper processes the first run
[ ] pending approval endpoint returns one proposal_id
[ ] approval message returns 202
[ ] worker helper processes the approval run
[ ] repeated send request returns 202
[ ] worker helper processes the send run
[ ] final transcript contains `Prepared outbound message: ...`
[ ] diagnostics/deliveries shows a sent delivery
[ ] node runner is running on port 8010
[ ] remote exec seed script creates approval state
[ ] signed request to /internal/node/exec returns completed
[ ] diagnostics/node-executions shows the audit row
```
