# Example: Local Deployment Orchestration With LLM-Driven Agents, Docker, MailDev, and Code Generation

This guide gives you a fully local, LLM-driven `python-claw` example running entirely in Docker. The only external credential is an OpenAI API key. Every agent decision — delegation, code generation, notification — is made by the LLM, not by helper scripts.

It showcases:

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

1. A user sends a message through the **webchat** adapter asking to deploy a made-up app.
2. The LLM (parent `default-agent`) decides to call `delegate_to_agent` targeting `deploy-agent`. This executes immediately (no approval needed).
3. The worker processes the `deploy-agent` child run. The child LLM proposes a `remote_exec` to POST to the local webhook receiver. An **approval prompt** is sent to the user.
4. The user sends `approve <proposal_id>` through webchat.
5. The worker re-runs the child. The approved `curl` command executes on the node-runner.
6. The user sends a deployment-complete callback via `curl`.
7. The user asks for a deploy report. The parent LLM delegates to `code-agent`.
8. `code-agent` proposes a `remote_exec` with `python3 -c` to generate files. The user approves.
9. Python runs in an isolated per-session workspace, creating `deploy_report.py` and `deploy_report.json`.
10. The user asks for email notification. The parent LLM delegates to `notify-agent`.
11. `notify-agent` proposes a `remote_exec` with `python3 -c` using `smtplib` to send email through **MailDev**. The user approves.
12. The email arrives in the MailDev web UI.

## How LLM-Driven Tool Use Works

### delegate_to_agent (no approval required)

The LLM sees `delegate_to_agent` as a callable function. When it calls it, the delegation is created and the child run is queued immediately. The system prompt tells the LLM: *"Delegation is asynchronous: queue bounded child work and continue without waiting for completion in the same turn."*

### remote_exec (approval required)

The LLM sees `remote_exec` and can propose invocations. But execution is blocked until the user approves:

```
1. Child LLM calls remote_exec({...})
2. System creates approval proposal, returns prompt to user:
   "Approval required for remote_exec. Proposal <id> is waiting. Reply: approve <id>"
3. User sends: "approve <id>"
4. New run queued → approval found → command executes on node-runner
```

This is the intended production UX — humans approve privileged actions before they run.

## Architecture

```
                                          ┌─────────────┐
                                          │  PostgreSQL  │
                                          └──────┬──────┘
                                                 │
User (curl) ──► [Webchat Adapter] ──► [Gateway :8000] ◄──► [Redis]
                                           │
                                      [Worker]  (continuous polling)
                                           │
                              ┌────────────┼────────────┐
                              │            │            │
                       [deploy-agent] [code-agent] [notify-agent]
                              │            │            │
                        remote_exec   remote_exec   remote_exec
                         (curl)       (python3)     (python3)
                              │            │            │
                              ▼            ▼            ▼
                   [Webhook Receiver] [Workspace]  [MailDev]
                    host:3001        .claw-sandboxes  SMTP 1025
                                                      Web 1080

All services run in Docker via docker-compose.
Webhook receiver and MailDev run on the host.
```

## Prerequisites

- **Docker** and **Docker Compose**
- **Node.js 18+** and **npm** (for MailDev and the webhook receiver)
- An **OpenAI API key**

Note: You do not need Python or `uv` installed locally. The gateway, worker, and node-runner all run inside Docker containers.

## Step 1: Install Local Tools

### 1.1 Install MailDev

```bash
npm install -g maildev
```

Verify:

```bash
maildev --version
```

### 1.2 Verify The Webhook Receiver

The repo includes [webhook-receiver.js](/webhook-receiver.js) in the root. It is a 25-line Node.js script that logs every POST to stdout:

```bash
node webhook-receiver.js
```

Verify in another terminal:

```bash
curl http://localhost:3001
```

Expected: `{"status":"webhook receiver running","received":0}`

## Step 2: Configure `.env`

```bash
cp .env.example .env
```

Replace the contents with the following. Change only `YOUR_OPENAI_API_KEY`:

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

PYTHON_CLAW_WORKER_POLL_SECONDS=2
PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30
```

### Configuration highlights

- **`NODE_RUNNER_MODE=http`** — the node-runner runs as a separate Docker service at `http://node-runner:8010`, giving true process isolation for `remote_exec`.
- **`/usr/bin/python3`** is in the allowed executables list so the node-runner can execute Python scripts.
- **`default-agent`** can delegate to `deploy-agent`, `code-agent`, and `notify-agent`. Each child has `remote_execution_enabled: true`.
- **`default-agent`** sees `echo_text` and `delegate_to_agent`. Child agents see `echo_text` and `remote_exec`. No agent sees tools it does not need.

## Step 3: Start Everything

### 3.1 Start MailDev (host terminal 1)

```bash
maildev --smtp 1025 --web 1080
```

Open [http://localhost:1080](http://localhost:1080) to see the empty inbox.

### 3.2 Start the webhook receiver (host terminal 2)

```bash
node webhook-receiver.js
```

### 3.3 Build and start Docker services (host terminal 3)

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build
```

Check all services are running:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml ps
```

You should see five containers:

| Container | Role |
|-----------|------|
| `python-claw-postgres` | Database |
| `python-claw-redis` | Cache |
| `python-claw-gateway` | API server (port 8000) |
| `python-claw-worker` | Continuous background worker |
| `python-claw-node-runner` | Isolated command executor (port 8010) |

### 3.4 Run database migrations

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml \
  run --rm gateway uv run alembic upgrade head
```

### 3.5 Verify health

```bash
curl http://localhost:8000/health/live
```

Expected: `{"status":"ok"}`

```bash
curl http://localhost:8000/health/ready -H 'Authorization: Bearer demo-operator-token'
```

Expected: JSON with `"status": "ok"` and dependency checks.

### 3.6 Watch worker logs

In a separate terminal, tail the worker container to see runs being processed:

```bash
docker logs -f python-claw-worker
```

Leave this running throughout the demo. You will see log lines every time the worker claims and processes a run.

## Step 4: Send The Deployment Request

Send a message through the webchat adapter:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Deploy the app northwind-api to staging. Delegate this to deploy-agent. The deploy-agent should use remote_exec to POST a JSON payload to http://host.docker.internal:3001/deploy-events with curl. The payload should include correlation_id=northwind-api-staging-001, event=deployment_started, app=northwind-api, environment=staging. Use correlation id northwind-api-staging-001."
  }'
```

Save the `session_id` from the `202` response:

```bash
export SESSION_ID="<paste session_id here>"
```

### What happens automatically

Watch the worker logs. Within a few seconds:

1. The worker claims the parent run.
2. The parent LLM receives the message and the list of available tools (`echo_text`, `delegate_to_agent`).
3. The LLM calls `delegate_to_agent(child_agent_id="deploy-agent", task_text="...", delegation_kind="deployment")`.
4. The delegation is created. A child session and child run are queued.
5. The worker processes the child run.
6. The child LLM (`deploy-agent`) sees `remote_exec` as an available tool and proposes a `curl` command.
7. The system creates an approval proposal and returns a prompt to the user.

## Step 5: Check For The Approval Prompt

Poll the webchat for the assistant's responses:

```bash
curl -s "http://localhost:8000/providers/webchat/accounts/webchat-demo/poll?stream_id=demo-user&limit=50" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | python3 -m json.tool
```

You should see messages including an approval prompt like:

> Approval required for `remote_exec`. Proposal `<proposal_id>` is waiting for approval. Reply `approve <proposal_id>` to proceed.

Copy the `<proposal_id>`.

## Step 6: Approve The Deployment Action

Send the approval through webchat:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "approve <paste-proposal-id-here>"
  }'
```

### What happens automatically

1. The approval is recorded in the database.
2. A new child run is queued.
3. The worker processes it. The `remote_exec` approval is now found.
4. The `curl` command executes on the node-runner container, POSTing to `host.docker.internal:3001`.
5. The child run completes. A parent continuation run is queued.
6. The parent LLM receives the delegation result.

### Verify

Check the webhook receiver terminal. You should see:

```
--- Webhook #1 received at 2026-03-29T... ---
Path: /deploy-events
Body: {"correlation_id":"northwind-api-staging-001","event":"deployment_started",...}
---
```

## Step 7: Send The Deployment Callback

Simulate the external deployment system completing:

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

The callback uses `peer_id: "demo-user"` to route into the **same parent session**. The worker will process this and the parent LLM will see the callback in its transcript context.

## Step 8: Request A Deploy Report (Code Generation)

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "The deployment completed. Now delegate to code-agent to generate a Python deployment report. The code-agent should use remote_exec with python3 -c to: 1) write a deploy_report.json file containing app=northwind-api, environment=staging, status=completed, correlation_id=northwind-api-staging-001, and a generated_at timestamp, 2) write a deploy_report.py script that reads and prints the JSON report, 3) execute the script and print the output."
  }'
```

### What happens

1. Parent LLM delegates to `code-agent`.
2. `code-agent` proposes a `remote_exec` with `python3 -c "{code}"`.
3. Approval prompt returned to user.

## Step 9: Approve The Code Generation

Poll for the approval prompt:

```bash
curl -s "http://localhost:8000/providers/webchat/accounts/webchat-demo/poll?stream_id=demo-user&limit=50" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | python3 -m json.tool
```

Find the new proposal ID and approve:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "approve <paste-proposal-id-here>"
  }'
```

### Verify the generated files

The Python script runs inside the node-runner container in a per-session workspace. To inspect the files:

```bash
docker exec python-claw-node-runner find /app/.claw-sandboxes/sessions/code-agent/ -type f
```

Read the generated report:

```bash
docker exec python-claw-node-runner cat /app/.claw-sandboxes/sessions/code-agent/*/deploy_report.json
```

Expected:

```json
{
  "app": "northwind-api",
  "environment": "staging",
  "status": "completed",
  "correlation_id": "northwind-api-staging-001",
  "generated_at": "2026-03-29T..."
}
```

Run the generated script:

```bash
docker exec python-claw-node-runner python3 /app/.claw-sandboxes/sessions/code-agent/*/deploy_report.py
```

## Step 10: Request Email Notification

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Now delegate to notify-agent to send a deployment-complete notification email. The notify-agent should use remote_exec with python3 -c to send an email using smtplib to host.docker.internal port 1025. From: python-claw@localhost, To: ops-team@localhost, Subject: Deployment complete northwind-api staging, Body: The deployment for northwind-api completed successfully. Correlation id: northwind-api-staging-001."
  }'
```

## Step 11: Approve The Email Action

Poll and approve as before:

```bash
curl -s "http://localhost:8000/providers/webchat/accounts/webchat-demo/poll?stream_id=demo-user&limit=50" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | python3 -m json.tool
```

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "demo-user",
    "peer_id": "demo-user",
    "content": "approve <paste-proposal-id-here>"
  }'
```

### Verify the email

Open [http://localhost:1080](http://localhost:1080). You should see an email:

- **From:** python-claw@localhost
- **To:** ops-team@localhost
- **Subject:** Deployment complete northwind-api staging
- **Body:** The deployment for northwind-api completed successfully. Correlation id: northwind-api-staging-001.

## Step 12: Inspect The Full Audit Trail

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'

# Parent session and transcript
curl -s "$BASE/sessions/$SESSION_ID" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/sessions/$SESSION_ID/messages" -H "$AUTH" | python3 -m json.tool

# All runs (parent + children)
curl -s "$BASE/sessions/$SESSION_ID/runs" -H "$AUTH" | python3 -m json.tool

# Delegations from parent to children
curl -s "$BASE/sessions/$SESSION_ID/delegations" -H "$AUTH" | python3 -m json.tool

# System-wide diagnostics
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool
```

What you should see:

| Record | Description |
|--------|-------------|
| Parent session | Webchat-originated, owned by `default-agent` |
| Delegation to `deploy-agent` | Child session, child runs (proposal + approved execution) |
| Node execution audit (curl) | POST to webhook receiver, exit code 0 |
| Callback message | `deployment_callback` re-entering the parent session |
| Delegation to `code-agent` | Child session, child runs |
| Node execution audit (python3) | Script generation, exit code 0 |
| Delegation to `notify-agent` | Child session, child runs |
| Node execution audit (python3) | smtplib email send, exit code 0 |
| Outbound deliveries | Webchat responses at each stage |

## What This Demo Proves

| Capability | How demonstrated |
|-----------|----------------|
| Gateway-first routing | All traffic enters via `/providers/webchat/.../messages` or `/inbound/message` |
| Durable sessions | Same session persists across messages, callback, and delegations |
| Continuous worker | Docker worker container processes runs automatically |
| LLM-driven delegation | Parent LLM autonomously calls `delegate_to_agent` |
| LLM-driven tool use | Child LLMs autonomously propose `remote_exec` invocations |
| Approval governance | `remote_exec` blocked until user approves; exact proposal reviewed |
| Remote execution (curl) | Node-runner executes curl in isolated container |
| Remote execution (python3) | Node-runner executes Python in isolated container with workspace |
| Code generation | `code-agent` writes files to per-session workspace |
| Callback re-entry | External callback resumes workflow in same session |
| Production auth | Admin/diagnostics routes require bearer token |
| Rate limiting | Quota enforcement active on all inbound routes |
| Full observability | Every step auditable via diagnostics APIs |

## Troubleshooting

### LLM does not delegate

The LLM may not follow instructions precisely on the first try. Check what it decided:

```bash
curl -s "http://localhost:8000/sessions/$SESSION_ID/messages" \
  -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
```

If it replied with text instead of delegating, send a follow-up message being more direct: *"Use the delegate_to_agent tool to delegate this to deploy-agent now."*

### No approval prompt appears

Check that the child agent's tool profile includes `remote_exec` and that `remote_execution_enabled` is `true` in the child's policy profile. Verify worker logs for errors:

```bash
docker logs python-claw-worker --tail 50
```

### Webhook receiver shows no requests

The node-runner runs inside Docker. It reaches the host via `host.docker.internal`. On Linux, you may need to add this to the node-runner service in `docker-compose.app.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### MailDev shows no email

Same `host.docker.internal` consideration. Also verify MailDev is listening:

```bash
curl http://localhost:1080
```

And test SMTP directly from the node-runner container:

```bash
docker exec python-claw-node-runner python3 -c "
import smtplib
from email.message import EmailMessage
msg = EmailMessage()
msg['From'] = 'test@test'
msg['To'] = 'test@test'
msg['Subject'] = 'test'
msg.set_content('hello')
with smtplib.SMTP('host.docker.internal', 1025) as s:
    s.send_message(msg)
print('sent')
"
```

### python3 not found in node-runner

Verify the allowed executables and that the container has Python:

```bash
docker exec python-claw-node-runner which python3
```

The Dockerfile is based on `python:3.11-slim`, so `/usr/local/bin/python3` is available. If the path differs, update `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES`.

### Callback created a new session instead of resuming

The callback must use the same routing tuple as the original session:
- `channel_kind`: `webchat`
- `channel_account_id`: `webchat-demo`
- `peer_id`: `demo-user`

If `peer_id` differs, a new session is created.

## Cleanup

```bash
# Stop Docker services
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml down

# Stop MailDev and webhook receiver (Ctrl+C in their terminals)

# Remove volumes for a fresh start
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml down -v
```

## Files Created For This Example

| File | Purpose |
|------|---------|
| [Dockerfile](/Dockerfile) | Builds the python-claw image used by gateway, worker, and node-runner |
| [docker-compose.app.yml](/docker-compose.app.yml) | Adds gateway, worker, and node-runner services to the Docker stack |
| [scripts/worker_loop.py](/scripts/worker_loop.py) | Continuous worker daemon with graceful shutdown |
| [webhook-receiver.js](/webhook-receiver.js) | Local webhook receiver (25-line Node.js script) |

## Extending This Example

### Add Telegram ingress

1. Create a bot via `@BotFather`, get the token
2. Add a `telegram-prod` entry to `PYTHON_CLAW_CHANNEL_ACCOUNTS`
3. Expose port 8000 publicly (e.g., `ngrok http 8000`)
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

Web UI at [http://localhost:5678](http://localhost:5678). Create webhook-triggered workflows that python-claw's agents can invoke.
