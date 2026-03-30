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

Run database migrations:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml \
  run --rm gateway uv run alembic upgrade head
```

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
   - The parent agent confirms it is delegating to `deploy-agent`.
   - A user-friendly approval message appears explaining that `deploy-agent` is ready to run the deployment command, but needs approval first.
   - The message includes:
     - the action name `remote_exec`
     - the proposal ID on its own line
     - the exact approval command to type
   - If you only see `Received: ...`, the app is still using the rule-based profile from older database state. Go back to Step 3 and run the `down -v` reset before starting the stack again.

## Step 5: Chat — Approve The Deployment Action

Copy the proposal ID from the approval message in the chat, then type:

```
approve <paste-proposal-id-here>
```

### What happens

1. The approval is recorded and the `remote_exec` action is activated.
2. The system automatically enqueues a continuation run for `deploy-agent` — **you do not need to resend the original message**.
3. Within a few seconds the worker picks up the continuation, the `curl` command executes on the node-runner, and the parent agent receives the delegation result.
4. Check **Terminal 2** (webhook receiver) — you should see:

```
--- Webhook #1 received at 2026-03-29T... ---
Path: /deploy-events
Body: {"correlation_id":"northwind-api-staging-001","event":"deployment_started",...}
---
```

5. The parent agent responds in the chat confirming the deployment command ran.

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

The callback uses `peer_id: "demo-user"` to route into the **same session**. The parent LLM will see it in the chat transcript.

## Step 7: Chat — Request A Deploy Report

Back in the browser chat, type:

```
The deployment completed. Now delegate to code-agent to generate a Python deployment report. The code-agent should use remote_exec with python3 -c to write a deploy_report.json with app=northwind-api, environment=staging, status=completed, correlation_id=northwind-api-staging-001, and a generated_at timestamp. Also write a deploy_report.py script that reads and prints the JSON. Execute the script and show the output.
```

Wait for the approval message with the proposal ID, then type:

```
approve <paste-proposal-id-here>
```

### Verify the generated files

```bash
docker exec python-claw-node-runner find /app/.claw-sandboxes/sessions/code-agent/ -type f 2>/dev/null
docker exec python-claw-node-runner cat /app/.claw-sandboxes/sessions/code-agent/*/deploy_report.json 2>/dev/null
```

## Step 8: Chat — Request Email Notification

In the browser chat, type:

```
Now delegate to notify-agent to send a deployment-complete email. The notify-agent should use remote_exec with python3 -c to send an email using smtplib to host.docker.internal port 1025. From: python-claw@localhost, To: ops-team@localhost, Subject: Deployment complete northwind-api staging, Body: The deployment for northwind-api completed successfully. Correlation id: northwind-api-staging-001.
```

Wait for the approval message with the proposal ID, then type:

```
approve <paste-proposal-id-here>
```

### Verify the email

Open [http://localhost:1080](http://localhost:1080). You should see the email in MailDev.

## Step 9: Inspect The Audit Trail

Use the admin APIs to inspect everything that happened:

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'

# Session
curl -s "$BASE/agents/default-agent/sessions" -H "$AUTH" | python3 -m json.tool

# Messages (full transcript)
curl -s "$BASE/sessions/<SESSION_ID>/messages" -H "$AUTH" | python3 -m json.tool

# Delegations
curl -s "$BASE/sessions/<SESSION_ID>/delegations" -H "$AUTH" | python3 -m json.tool

# All runs
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool

# Node execution audits
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool

# Outbound deliveries
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool
```

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
