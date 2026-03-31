# Example: Local Deployment Orchestration With LLM-Driven Agents, Browser Chat UI, Docker, and MailDev

This guide gives you a fully local, LLM-driven `python-claw` example running entirely in Docker with a **browser-based chat interface**. No curl commands for user interaction. The only external credential is an OpenAI API key.

It showcases:

- **browser-based webchat UI** for all user interaction
- gateway-first inbound routing and durable sessions
- async worker-owned execution runs (continuous background worker)
- LLM-driven tool selection for all agents (parent and children)
- durable sub-agent delegation via `delegate_to_agent`
- approval-gated `remote_exec` through the node-runner
- code generation and execution in an isolated workspace
- callback-driven workflow continuation
- production auth, diagnostics, and quota enforcement
- full Docker Compose stack (gateway, worker, node-runner, PostgreSQL, Redis)

## Scenario

1. You open the webchat UI in your browser and type a deployment request.
2. The parent LLM (`default-agent`) calls `delegate_to_agent` targeting `deploy-agent` (no approval needed).
3. `deploy-agent` proposes a `remote_exec` to POST to the local webhook receiver. An approval prompt appears in the chat.
4. You type `approve <proposal_id>` in the chat.
5. The system automatically continues — the `curl` command runs on the node-runner without you resending anything. The webhook receiver logs the POST.
6. You send a deployment callback via `curl` (the one machine-to-machine step).
7. You ask for a deploy report in the chat. The parent LLM delegates to `code-agent`.
8. `code-agent` proposes `python3 -c` code. You approve in the chat. The code runs automatically.
9. Python generates `deploy_report.py` and `deploy_report.json` in an isolated workspace.
10. You ask for email notification. The parent LLM delegates to `notify-agent`.
11. `notify-agent` proposes `python3 -c` with `smtplib`. You approve. The email sends automatically.
12. The email arrives in the MailDev web UI.

## Architecture

```
Browser (webchat.html)
    |
    v  HTTP (send + poll)
[Gateway :8000] ──► [PostgreSQL]
    |
[Worker] (continuous)
    |
 ┌──┼──┐
 |  |  |
[deploy] [code] [notify]
 |  |  |
 v  v  v
[Webhook   [Workspace]   [MailDev]
 :3001]    .claw-sandboxes SMTP :1025
                           Web :1080

Docker: gateway, worker, node-runner, postgres, redis
Host:   webchat.html (served via npx serve), maildev, webhook-receiver
```

## Prerequisites

- **Docker** and **Docker Compose**
- **Node.js 18+** and **npm**
- An **OpenAI API key**

You do not need Python or `uv` locally. All python-claw services run inside Docker.

## Step 1: Install Host Tools

### 1.1 Install MailDev

```bash
npm install -g maildev
```

### 1.2 Install serve (for the chat UI)

```bash
npm install -g serve
```

Both are one-time global installs.

## Step 2: Prepare `.env` From `.env.demo`

For this example, `.env.demo` is the source configuration file. The compose files load `.env`, so the first step is:

```bash
cp .env.demo .env
```

Then edit `.env.demo` and update only the OpenAI API key value:

```text
PYTHON_CLAW_APP_NAME=python-claw-gateway

PYTHON_CLAW_POSTGRES_DB=openassistant
PYTHON_CLAW_POSTGRES_USER=openassistant
PYTHON_CLAW_POSTGRES_PASSWORD=openassistant
PYTHON_CLAW_POSTGRES_PORT=5432
PYTHON_CLAW_REDIS_PORT=6379

PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@postgres:5432/openassistant

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
PYTHON_CLAW_NODE_RUNNER_MODE=http
PYTHON_CLAW_NODE_RUNNER_BASE_URL=http://node-runner:8010
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=local-demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=local-demo-signing-secret
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=local-demo-node-token
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env,/usr/local/bin/python3
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
PYTHON_CLAW_WEBCHAT_INTERACTIVE_APPROVALS_ENABLED=true

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

PYTHON_CLAW_WORKER_POLL_SECONDS=2
PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30

PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES=[{"agent_id":"deploy-agent","executable":"/usr/bin/curl","argv_template":["-s","-X","POST","-H","Content-Type: application/json","-d","{json_payload}","{url}"],"timeout_seconds":15,"sandbox_profile_key":"shared-default","workspace_binding_kind":"none","workspace_mount_mode":"none"},{"agent_id":"code-agent","executable":"/usr/local/bin/python3","argv_template":["-c","{script}"],"timeout_seconds":30,"sandbox_profile_key":"shared-default","workspace_binding_kind":"agent","workspace_mount_mode":"rw"},{"agent_id":"notify-agent","executable":"/usr/local/bin/python3","argv_template":["-c","{script}"],"timeout_seconds":30,"sandbox_profile_key":"shared-default","workspace_binding_kind":"none","workspace_mount_mode":"none"}]
```

After editing `.env.demo`, copy it to `.env` again before running any Docker commands:

```bash
cp .env.demo .env
```

### Configuration highlights

- **`NODE_RUNNER_MODE=http`** — the node-runner runs as a separate Docker service, giving true process isolation.
- **`/usr/local/bin/python3`** in allowed executables — this is the path inside the `python:3.11-slim` Docker image.
- **`default-agent`** can delegate to `deploy-agent`, `code-agent`, and `notify-agent`.
- **`default-agent`** sees `echo_text` and `delegate_to_agent`. Child agents see `echo_text` and `remote_exec`.
- **`PYTHON_CLAW_REMOTE_EXEC_AGENT_TEMPLATES`** — registers a pre-approved `NodeCommandTemplate` for each child agent at startup. This tells the node-runner exactly which executable and argument template to use (e.g. `/usr/bin/curl` with `{url}` and `{json_payload}` placeholders for `deploy-agent`), and allows the LLM to discover the required argument names automatically.

## Step 3: Start Everything

Make sure you already copied `.env.demo` to `.env` before this step. Docker Compose reads `.env`, not `.env.demo`.

You will have **five terminals** open:

### Terminal 1 — MailDev

```bash
maildev --smtp 1025 --web 1080
```

Open [http://localhost:1080](http://localhost:1080) to see the empty inbox.

### Terminal 2 — Webhook Receiver

```bash
node webhook-receiver.js
```

You should see: `Webhook receiver listening on http://localhost:3001`

### Terminal 3 — Docker (python-claw stack)

If you previously ran the project with a different `.env` or in `rule_based` mode, reset the stack and volumes first so the demo agent/model profiles are recreated from `.env.demo`:

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml down -v
```

Start PostgreSQL and Redis first:

```bash
docker compose --env-file .env -f docker-compose.yml up -d postgres redis
```

Wait until both are healthy:

```bash
docker compose --env-file .env -f docker-compose.yml ps
```

Verify that the `openassistant` database exists:

```bash
docker exec -it python-claw-postgres psql -U openassistant -d postgres -c '\l'
```

You should see `openassistant` in the database list. If it is missing, create it manually:

```bash
docker exec -it python-claw-postgres psql -U openassistant -d postgres -c 'CREATE DATABASE openassistant;'
```

Run database migrations:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml \
  run --rm gateway uv run alembic upgrade head
```

The migration command creates the schema and tables inside the database. It does not create the PostgreSQL database itself.

Then build and start the application services:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build
```

Verify:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml ps
```

You should see five containers: `postgres`, `redis`, `gateway`, `worker`, `node-runner`.

Tail the worker logs (keep this running):

```bash
docker logs -f python-claw-worker
```

### Terminal 4 — Gateway Logs

Tail the gateway logs (keep this running):

```bash
docker logs -f python-claw-gateway
```

### Terminal 5 — Webchat UI

```bash
cd example
npx serve -l 3000 .
```

Open [http://localhost:3000/webchat.html](http://localhost:3000/webchat.html) in your browser.

The chat UI will automatically connect to the gateway. You should see a green "connected" badge and a system message: `Connected to http://localhost:8000 as demo-user`.

## Step 4: Chat — Request The Deployment

In the browser chat, type:

```
Deploy the app northwind-api to staging.
Delegate this to deploy-agent.
The deploy-agent should use remote_exec to POST to the webhook.
Call remote_exec with these exact arguments:
- url: http://host.docker.internal:3001/deploy-events
- json_payload: {"correlation_id":"northwind-api-staging-001","event":"deployment_started","app":"northwind-api","environment":"staging"}
```

Press Enter (or click Send).

### What you will see

1. Your message appears on the right (blue bubble).
2. The session ID appears as a system message.
3. Within a few seconds, assistant responses appear on the left:
   - The parent agent first shows a queued delegation message such as:

```text
Queued bounded delegation to `deploy-agent` as `<delegation-id>`.

Requested work:
Deploy the app northwind-api to staging using remote_exec to POST to the webhook.

Expected output:
Deployment initiated
```

   - Then a user-friendly approval message appears showing what `deploy-agent` is trying to do, for example:

```text
`deploy-agent` prepared the next step, but it needs your approval before it can continue.

Requested work:
Deploy the app northwind-api to staging using remote_exec to POST to the webhook.

Pending approvals:
1. Action: `remote_exec`
   Purpose: POST to `http://host.docker.internal:3001/deploy-events`.
   Proposal ID: `<proposal-id>`
   To approve: `approve <proposal-id>`

Reply with the approval command for the proposal you want to activate.
After approval, the delegated agent will continue automatically.
```

   - If you only see `Received: ...`, the app is still using the rule-based profile from older database state. Go back to Step 3 and run the `down -v` reset before starting the stack again.

## Step 5: Chat — Approve The Deployment Action

Copy the proposal ID from the approval message in the chat, then type:

```
approve <paste-proposal-id-here>
```

### What happens

1. The approval is recorded and the `remote_exec` action is activated. The chat confirms what you approved, for example:

```text
Approval recorded for proposal `<proposal-id>`.

You have authorized the system to: POST to `http://host.docker.internal:3001/deploy-events`.
`deploy-agent` is continuing automatically now, so you do not need to resend your original request.
```

2. The system automatically enqueues a continuation run for `deploy-agent` — **you do not need to resend the original message**.
3. Within a few seconds the worker picks up the continuation, the `curl` command executes on the node-runner, and the parent agent receives the delegation result.
4. Check **Terminal 2** (webhook receiver) — you should see:

```
--- Webhook #1 received at 2026-03-29T... ---
Path: /deploy-events
Body: {"correlation_id":"northwind-api-staging-001","event":"deployment_started",...}
---
```

5. The parent agent responds in the chat with a completion message that includes the original requested work and the result, for example:

```text
`deploy-agent` completed the delegated work.

Requested work:
Deploy the app northwind-api to staging using remote_exec to POST to the webhook.

Result:
Deployment curl command executed successfully.
```

## Step 6: Send The Deployment Callback

This is the one step done outside the chat UI, because it simulates an external system calling back. Run in any terminal:

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

What this command accomplishes:

- It simulates the external deployment system calling back into `python-claw`
- It creates a new inbound message on the same `webchat` session
- It lets the parent agent continue the workflow using the callback data

Example output:

```json
{
  "session_id": "3d0d8f26-7eb5-4bd9-b93d-4fe3c5b3794e",
  "message_id": 117,
  "run_id": "run-callback-001",
  "status": "queued",
  "dedupe_status": "accepted",
  "trace_id": "trace-callback-001"
}
```

Important output attributes:

- `session_id`: the session the callback was routed into; it should match the existing chat session
- `message_id`: the stored inbound callback message ID
- `run_id`: the execution run queued to process the callback
- `status`: the run state at acceptance time; typically `queued`
- `dedupe_status`: whether the callback was newly accepted or treated as a duplicate
- `trace_id`: the trace identifier you can use to correlate logs and diagnostics

If you send the exact same callback again with the same `external_message_id`, the response will usually show `dedupe_status: "duplicate"` and point to the original session/message/run instead of creating a new one.

The callback uses `peer_id: "demo-user"` to route into the **same session**. The parent LLM will see it in the chat transcript.

## Step 7: Chat — Request A Deploy Report

Back in the browser chat, copy and paste:

```
The deployment completed.
Delegate to code-agent.

Use exactly one remote_exec call with one python3 -c script payload.
Do not split this into multiple remote_exec calls.

In that single script:
- write deploy_report.json with:
- app: northwind-api
- environment: staging
- status: completed
- correlation_id: northwind-api-staging-001
- generated_at: current timestamp
- write deploy_report.py that reads and prints the JSON
- execute deploy_report.py
- show the script output
```

You should normally see a single approval message with one proposal ID. Then type:

```
approve <paste-proposal-id-here>
```

You should see the same message pattern as in Steps 4 and 5:

- A queued delegation message, for example:

```text
Queued bounded delegation to `code-agent` as `<delegation-id>`.

Requested work:
The deployment completed. Delegate to code-agent to generate a Python deployment report.
```

- An approval message, for example:

```text
`code-agent` prepared the next step, but it needs your approval before it can continue.

Requested work:
The deployment completed. Delegate to code-agent to generate a Python deployment report.

Pending approvals:
1. Action: `remote_exec`
   Purpose: Generate `deploy_report.json`, write `deploy_report.py`, and run the report script.
   Proposal ID: `<proposal-id>`
   To approve: `approve <proposal-id>`
```

- After you approve, a confirmation message such as:

```text
Approval recorded for proposal `<proposal-id>`.

You have authorized the system to: Generate `deploy_report.json`, write `deploy_report.py`, and run the report script.
`code-agent` is continuing automatically now, so you do not need to resend your original request.
```

- Then a completion message such as:

```text
`code-agent` completed the delegated work.

Requested work:
The deployment completed. Delegate to code-agent to generate a Python deployment report.

Result:
Python deployment report generated successfully.
```

### Verify the generated files

```bash
docker exec python-claw-node-runner sh -lc 'find /app/.claw-sandboxes/agents/code-agent -type f 2>/dev/null'
docker exec python-claw-node-runner sh -lc 'cat /app/.claw-sandboxes/agents/code-agent/deploy_report.json 2>/dev/null'
docker exec python-claw-node-runner sh -lc 'cat /app/.claw-sandboxes/agents/code-agent/deploy_report.py 2>/dev/null'
```

What these commands accomplish:

- The first command lists the files created in the `code-agent` writable workspace
- The second command shows the generated JSON deployment report
- The third command shows the generated Python script that reads and prints the JSON

Why this path is correct:

- `code-agent` uses an agent-bound workspace, so its files are written under `/app/.claw-sandboxes/agents/code-agent`
- The earlier `sessions/code-agent` path was incorrect for this demo configuration

Example output for the first command:

```text
/app/.claw-sandboxes/agents/code-agent/deploy_report.json
/app/.claw-sandboxes/agents/code-agent/deploy_report.py
```

What to look for:

- `deploy_report.json`: confirms the report file was written
- `deploy_report.py`: confirms the helper script was written

Example output for the second command:

```json
{"app": "northwind-api", "environment": "staging", "status": "completed", "correlation_id": "northwind-api-staging-001", "generated_at": "2026-03-31T13:50:02.481438"}
```

Important JSON attributes:

- `app`: the deployed application name
- `environment`: the deployment target environment
- `status`: the final deployment status
- `correlation_id`: the deployment workflow identifier tying the report back to the earlier steps
- `generated_at`: when the report file was generated

Example output for the third command:

```python
import json

with open("deploy_report.json", "r") as f:
    data = json.load(f)

print(data)
```

What to look for:

- The script reads `deploy_report.json`
- The script prints the parsed JSON object
- The script lives in the same workspace as the JSON file

If the first command returns nothing, `code-agent` likely printed a result without actually writing the files. In that case, the delegated script only partially followed the Step 7 request.

## Step 8: Chat — Request Email Notification

In the browser chat, copy and paste:

```
Delegate to notify-agent to send a deployment-complete email.

Use remote_exec with python3 -c and smtplib.

Send the email to host.docker.internal on port 1025.

Use these fields:
- From: python-claw@localhost
- To: ops-team@localhost
- Subject: Deployment complete northwind-api staging
- Body: The deployment for northwind-api completed successfully. Correlation id: northwind-api-staging-001.
```

Wait for the approval message with the proposal ID, then type:

```
approve <paste-proposal-id-here>
```

You should see the same message flow here as well:

- A queued delegation message, for example:

```text
Queued bounded delegation to `notify-agent` as `<delegation-id>`.

Requested work:
Delegate to notify-agent to send a deployment-complete email.
```

- An approval message, for example:

```text
`notify-agent` prepared the next step, but it needs your approval before it can continue.

Requested work:
Delegate to notify-agent to send a deployment-complete email.

Pending approvals:
1. Action: `remote_exec`
   Purpose: Send an email notification.
   Proposal ID: `<proposal-id>`
   To approve: `approve <proposal-id>`
```

- After approval, a confirmation message such as:

```text
Approval recorded for proposal `<proposal-id>`.

You have authorized the system to: Send an email notification.
`notify-agent` is continuing automatically now, so you do not need to resend your original request.
```

- Then a completion message such as:

```text
`notify-agent` completed the delegated work.

Requested work:
Delegate to notify-agent to send a deployment-complete email.

Result:
Email sent to ops-team@localhost.
```

### Verify the email

Open [http://localhost:1080](http://localhost:1080). You should see the email in MailDev.

## Step 9: Inspect The Audit Trail

Use the admin APIs to inspect everything that happened:

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'
```

### 9.1 List sessions for `default-agent`

This command lists the sessions owned by `default-agent`. Use it to find the session ID for the chat you just ran.

```bash
curl -s "$BASE/agents/default-agent/sessions" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "id": "3d0d8f26-7eb5-4bd9-b93d-4fe3c5b3794e",
    "channel_kind": "webchat",
    "channel_account_id": "webchat-demo",
    "owner_agent_id": "default-agent",
    "created_at": "2026-03-31T13:42:11.120Z",
    "updated_at": "2026-03-31T13:45:02.901Z"
  }
]
```

Important attributes:

- `id`: the session ID you will use in the next commands
- `channel_kind`: the transport type; this demo uses `webchat`
- `channel_account_id`: the configured webchat account; this demo uses `webchat-demo`
- `owner_agent_id`: the top-level agent for the session
- `created_at` / `updated_at`: when the session started and when it was last active

### 9.2 Fetch the full message transcript

This command shows every message in the session, including user messages, assistant responses, system messages, approvals, and delegated results.

```bash
curl -s "$BASE/sessions/<SESSION_ID>/messages" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "id": 101,
    "role": "user",
    "sender_id": "demo-user",
    "content": "Deploy the app northwind-api to staging.",
    "created_at": "2026-03-31T13:42:18.004Z"
  },
  {
    "id": 102,
    "role": "assistant",
    "sender_id": "default-agent",
    "content": "Queued bounded delegation to `deploy-agent` as `74f276be-c7fc-479c-a299-d446596ef257`.",
    "created_at": "2026-03-31T13:42:19.337Z"
  }
]
```

Important attributes:

- `id`: the message ID inside the session
- `role`: who the message is from, such as `user`, `assistant`, or `system`
- `sender_id`: the specific sender, such as `demo-user`, `default-agent`, or a system sender
- `content`: the actual text shown in the chat or emitted by the system
- `created_at`: when the message was stored

### 9.3 List delegations for the session

This command shows each child-agent delegation created from the parent session, including which specialist agent handled the task and its final status.

```bash
curl -s "$BASE/sessions/<SESSION_ID>/delegations" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "id": "74f276be-c7fc-479c-a299-d446596ef257",
    "child_agent_id": "deploy-agent",
    "delegation_kind": "bounded",
    "status": "completed",
    "task_text": "Deploy the app northwind-api to staging using remote_exec to POST to the webhook.",
    "created_at": "2026-03-31T13:42:19.331Z"
  }
]
```

Important attributes:

- `id`: the delegation ID shown in the queued delegation message
- `child_agent_id`: the specialist agent that received the work
- `delegation_kind`: the delegation type; in this example it is bounded delegated work
- `status`: the current lifecycle state such as `queued`, `awaiting_approval`, `completed`, or `failed`
- `task_text`: the exact delegated task description
- `created_at`: when the delegation was created

### 9.4 List all execution runs

This command shows the orchestration runs processed by the worker, including inbound message handling, approval continuations, and delegation result handling.

```bash
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "id": "run-001",
    "session_id": "3d0d8f26-7eb5-4bd9-b93d-4fe3c5b3794e",
    "agent_id": "default-agent",
    "trigger_kind": "inbound_message",
    "status": "completed",
    "created_at": "2026-03-31T13:42:18.010Z"
  }
]
```

Important attributes:

- `id`: the execution run ID
- `session_id`: the session this run belongs to
- `agent_id`: which agent executed the run
- `trigger_kind`: what started the run, such as `inbound_message`, `delegation_approval_prompt`, or `delegation_result`
- `status`: the run state, such as `queued`, `running`, `completed`, or `failed`
- `created_at`: when the run was created

### 9.5 Inspect node execution audits

This command shows the audited remote executions sent to the node-runner, including the child agent, tool capability, and execution outcome.

```bash
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "correlation_id": "9347d7c7-ff72-49d7-b327-3984b22cb387",
    "agent_id": "notify-agent",
    "capability_name": "remote_exec",
    "status": "completed",
    "created_at": "2026-03-31T13:44:41.551Z"
  }
]
```

Important attributes:

- `correlation_id`: the audit correlation ID, often aligned with the approval/delegation flow
- `agent_id`: the child agent that requested the remote execution
- `capability_name`: the governed capability; here it is `remote_exec`
- `status`: whether the remote execution completed or failed
- `created_at`: when the audit event was recorded

### 9.6 Inspect outbound deliveries

This command shows outbound delivery attempts created by the system, which is useful for understanding how assistant/system responses were delivered back to the chat channel.

```bash
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool
```

Example output:

```json
[
  {
    "delivery_id": "delivery-001",
    "session_id": "3d0d8f26-7eb5-4bd9-b93d-4fe3c5b3794e",
    "delivery_kind": "chat_message",
    "status": "sent",
    "created_at": "2026-03-31T13:44:42.102Z"
  }
]
```

Important attributes:

- `delivery_id`: the outbound delivery record ID
- `session_id`: the related session
- `delivery_kind`: the kind of outbound event, such as a chat message delivery
- `status`: the delivery state, such as `pending`, `sent`, or `failed`
- `created_at`: when the delivery record was created

## Webchat UI Features

The chat client ([webchat.html](/webchat.html)) is a single HTML file with no dependencies:

- **Auto-connect** on page load to the gateway health endpoint
- **Send messages** by pressing Enter (Shift+Enter for newline)
- **Auto-poll** for assistant responses (configurable interval, default 3 seconds)
- **Session tracking** — displays the session ID when first assigned
- **Delivery metadata** — each assistant message shows delivery ID, kind, and status
- **Toggle log panel** — click "toggle log" in the header to see raw HTTP requests
- **Configurable** — gateway URL, account ID, token, user ID, and poll interval are all editable in the config bar

The UI uses the webchat adapter's real HTTP API:
- `POST /providers/webchat/accounts/{id}/messages` to send
- `GET /providers/webchat/accounts/{id}/poll` to receive

## What This Demo Proves

| Capability | How demonstrated |
|-----------|----------------|
| Real chat interface | Browser-based webchat UI, not curl commands |
| Gateway-first routing | All traffic enters via webchat adapter or `/inbound/message` |
| Durable sessions | Same session across messages, callback, and all delegations |
| Continuous worker | Docker worker container auto-processes runs |
| LLM-driven delegation | Parent LLM autonomously calls `delegate_to_agent` |
| LLM-driven tool use | Child LLMs autonomously propose `remote_exec` |
| Approval governance | `remote_exec` blocked until user types `approve` in chat |
| Remote execution (curl) | Node-runner executes curl in isolated container |
| Remote execution (python3) | Node-runner executes Python in isolated container |
| Code generation | `code-agent` writes files to per-session workspace |
| Email delivery | `notify-agent` sends via smtplib to MailDev |
| Callback re-entry | External callback resumes workflow in same session |
| Production auth | Admin/diagnostics routes require bearer token |
| Rate limiting | Quota enforcement active on all inbound routes |
| Full observability | Every step auditable via diagnostics APIs |

## Troubleshooting

### Chat shows "Connection failed"

Verify the gateway is running:

```bash
curl http://localhost:8000/health/live
```

If using a non-default port, update the Gateway field in the chat config bar and click Connect.

### Chat shows no assistant responses

1. Check the worker is running: `docker logs python-claw-worker --tail 20`
2. Click "toggle log" in the chat header to see poll responses
3. Increase poll frequency (lower the ms value in config bar)

### LLM does not delegate

Send a follow-up: *"Use the delegate_to_agent tool to delegate this to deploy-agent now."*

### Webhook receiver or MailDev not reachable from Docker

On Linux, add this to the `node-runner` service in `docker-compose.app.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### python3 path mismatch

The Docker image uses `python:3.11-slim` where python3 is at `/usr/local/bin/python3`. Verify:

```bash
docker exec python-claw-node-runner which python3
```

Update `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES` if the path differs.

### CORS errors in browser

The webchat UI makes requests directly to the gateway. If you see CORS errors, the gateway may need CORS middleware. As a workaround, run the chat UI on the same origin by proxying, or add CORS headers to the gateway.

For a quick fix, you can use a browser extension to allow CORS, or start Chrome with:

```bash
# macOS
open -a "Google Chrome" --args --disable-web-security --user-data-dir=/tmp/chrome-cors
```

## Cleanup

```bash
# Stop Docker
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml down

# Stop MailDev, webhook receiver, and serve (Ctrl+C in their terminals)

# Remove volumes for a fresh start
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml down -v
```

## Files For This Example

| File | Purpose |
|------|---------|
| [webchat.html](/webchat.html) | Browser chat client (single HTML file, no dependencies) |
| [Dockerfile](/Dockerfile) | Builds the python-claw image for gateway, worker, and node-runner |
| [docker-compose.app.yml](/docker-compose.app.yml) | Adds gateway, worker, and node-runner to Docker stack |
| [scripts/worker_loop.py](/scripts/worker_loop.py) | Continuous worker daemon with graceful shutdown |
| [webhook-receiver.js](/webhook-receiver.js) | Local webhook receiver (Node.js) |

## Extending This Example

### Add Telegram ingress

1. Create a bot via `@BotFather`
2. Add a `telegram-prod` entry to `PYTHON_CLAW_CHANNEL_ACCOUNTS`
3. Expose port 8000 via `ngrok http 8000`
4. Set the webhook: `curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" -d '{"url":"https://<ngrok>/providers/telegram/webhook/telegram-prod"}'`

### Add real Slack notifications

1. Create a Slack app, enable Incoming Webhooks
2. Have `notify-agent` use `remote_exec` with `curl` to POST to the webhook URL

### Replace MailDev with Mailpit

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
```

Web UI at [http://localhost:8025](http://localhost:8025).

### Use n8n for complex automations

```bash
npx n8n start
```

Web UI at [http://localhost:5678](http://localhost:5678).
