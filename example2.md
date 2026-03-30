# Example: Local Deployment Orchestration With Webchat, MailDev, Code Generation, and a Local Webhook Receiver

This guide gives you a fully local, reproducible `python-claw` reference example that you can run on a single machine with no external accounts, no public internet exposure, and no third-party API keys beyond an OpenAI key.

It showcases:

- gateway-first inbound routing and durable sessions
- async worker-owned execution runs
- provider-backed tool use (OpenAI)
- durable sub-agent delegation (three sub-agents)
- remote execution through the node-runner
- **code generation and execution** via a specialist sub-agent
- production hardening around auth, diagnostics, and quotas
- callback-driven workflow continuation

## Scenario

1. A user sends a message through the **webchat** adapter asking to deploy a made-up app.
2. The parent assistant (`default-agent`) delegates the deployment work to `deploy-agent`.
3. `deploy-agent` uses `remote_exec` to POST a "deployment started" event to a **local webhook receiver**.
4. The user sends a `curl` callback into `python-claw` when the deployment is complete.
5. The parent assistant delegates to `code-agent` to **generate a Python deploy-report script** and execute it in an isolated workspace.
6. The parent assistant delegates a notification task to `notify-agent`.
7. `notify-agent` uses `remote_exec` to send a completion email via **MailDev** (local SMTP with web UI).

## Why This Is Better Than The Telegram/Slack/Gmail Example

| Concern | Original example.md | This example |
|---------|---------------------|--------------|
| External accounts | Telegram bot, Slack app, Google Apps Script, webhook.site | None (only OpenAI API key) |
| Public internet | Telegram requires a public webhook URL (ngrok or VPS) | Everything runs on localhost |
| Complexity | 9 external values to gather, 3 OAuth/bot setups | 1 API key, everything else is local |
| Reproducibility | Depends on external service availability | Fully deterministic local stack |
| Observability | Must check webhook.site, Slack channel, Gmail inbox separately | MailDev web UI at localhost:1080, webhook receiver stdout, workspace files on disk, python-claw admin APIs |

## Alternative Integration Options Considered

Before settling on this stack, these alternatives were evaluated:

| Tool | Type | Verdict |
|------|------|---------|
| **MailDev** (npm) | Local SMTP + web UI | Selected. Zero-config email capture, web UI for visual verification |
| **Mailpit** (Go binary / Docker) | Local SMTP + web UI | Good alternative to MailDev. Slightly heavier but has a REST API. Use if you prefer Docker-only |
| **json-server** (npm) | Fake REST API from a JSON file | Considered for webhook receiver. Works but is designed for REST CRUD, not webhook capture |
| **Express** (npm) | Custom webhook receiver script | Selected. 15-line script, logs every POST body to stdout |
| **n8n** (npm / Docker) | Workflow automation platform | Too heavy for a demo. Good if you want to build real automations on top of python-claw |
| **ntfy** (Docker) | Push notification service | Interesting for mobile push demos. Adds Docker complexity |
| **smee-client** (npm) | Webhook proxy / relay | Designed for GitHub webhooks. Overkill for local use |
| **Slack (fake mode)** | Built-in python-claw adapter | Already in the codebase. Use `mode: fake` for no-setup Slack testing, but outbound delivery goes nowhere visible |
| **Telegram (fake mode)** | Built-in python-claw adapter | Same as Slack fake mode. Good for testing routing logic, but nothing visible happens |

**Bottom line:** For a demo that someone can actually see working end-to-end on their laptop, `MailDev` + a tiny webhook receiver + the built-in webchat adapter + Python code generation is the simplest stack with the most visual feedback.

## Architecture

```
User (curl)
    |
    v
[Webchat Adapter]  -->  [Gateway API :8000]  -->  [PostgreSQL]
                              |
                              v
                         [Worker]  (polls queue, runs assistant graph)
                              |
                  +-----------+-----------+
                  |           |           |
           [deploy-agent] [code-agent] [notify-agent]
                  |           |           |
           remote_exec   remote_exec   remote_exec
            (curl)       (python3)      (curl)
                  |           |           |
                  v           v           v
       [Webhook       [Session       [MailDev SMTP :1025
        Receiver       Workspace]     / Web :1080]
        :3001]         .claw-sandboxes/
                       sessions/code-agent/<sid>/
                         deploy_report.py
                         deploy_report.json
```

- **Webchat** is the user-facing channel (built-in, no setup).
- **default-agent** is the parent assistant.
- **deploy-agent** uses `remote_exec` to POST to the local webhook receiver via `curl`.
- **code-agent** uses `remote_exec` to run `python3 -c "{code}"` in an isolated per-session workspace, generating files on disk.
- **notify-agent** uses `remote_exec` to send email through MailDev's SMTP relay via `curl`.
- The user sends a callback via `curl` to `POST /inbound/message` to resume the workflow.

## How Code Generation Works In python-claw

The `code-agent` creates and executes Python scripts through the node-runner's `remote_exec` tool. Here is how the pieces fit together:

### The command template

An approved `NodeCommandTemplate` defines the shape of allowed execution:

```python
NodeCommandTemplate(
    executable="/usr/bin/python3",
    argv_template=["-c", "{code}"],
    workspace_binding_kind="session",     # isolated per-session directory
    workspace_mount_mode="read_write",    # script can create files
    timeout_seconds=15,
    typed_action_id="tool.remote_exec",
    sandbox_profile_key="default",
)
```

### How argument substitution works

The `argv_template` uses Python's `str.format_map()`. The `{code}` placeholder gets replaced by the value the agent passes:

- Arguments: `{"code": "open('report.py', 'w').write('print(42)')"}`
- Resulting argv: `["/usr/bin/python3", "-c", "open('report.py', 'w').write('print(42)')"]`

Curly braces inside the substituted value (like Python dicts) are safe because `format_map` does not re-process substituted content.

### Workspace isolation

Each session gets its own directory under `.claw-sandboxes/sessions/code-agent/<session-id>/`. The `python3` subprocess runs with `cwd` set to this workspace. Any files the script creates land in this isolated directory and persist across runs within the same session.

### Approval gate

`remote_exec` requires approval. Each unique set of arguments goes through the approval gate:

- For this demo, the LLM proposes a specific `remote_exec` invocation with exact code.
- The user sees the proposed code and approves or denies it.
- The node-runner only executes after approval is verified.

### Execution constraints

| Constraint | Detail |
|-----------|--------|
| No shell | `subprocess.run(shell=False)` — no pipes, redirects, or `&&` chaining |
| Shell wrappers blocked | `sh`, `bash`, `zsh` are denied by policy |
| Scalar args only | Arguments must be flat (string, int, float, bool, null) |
| Workspace isolation | Per-session directory; files persist across runs in that session |
| Timeout enforced | `subprocess.run(timeout=15)` kills long-running scripts |
| Output captured | stdout/stderr captured (2000 char preview) and returned to the agent |

## Prerequisites

- **Python 3.11+** with [uv](https://docs.astral.sh/uv/) installed
- **Docker** and **Docker Compose** (for PostgreSQL and Redis)
- **Node.js 18+** and **npm** (for MailDev and the webhook receiver)
- An **OpenAI API key** (for provider-backed LLM turns)

## Step 1: Install The Local npm Tools

### 1.1 Install MailDev

MailDev is a zero-config local SMTP server with a web interface. Every email sent to it is captured and viewable in your browser.

```bash
npm install -g maildev
```

Verify it installed:

```bash
maildev --version
```

### 1.2 Create The Webhook Receiver

Create a file called `webhook-receiver.js` in the repo root:

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

This is a 25-line Node.js script that logs every POST body to stdout. No frameworks needed.

## Step 2: Start Infrastructure

### 2.1 Start PostgreSQL and Redis

```bash
docker compose --env-file .env up -d
```

Verify both are healthy:

```bash
docker compose ps
```

You should see `python-claw-postgres` and `python-claw-redis` both healthy.

### 2.2 Start MailDev

Open a new terminal:

```bash
maildev --smtp 1025 --web 1080
```

Verify the web UI is running by opening [http://localhost:1080](http://localhost:1080) in your browser. You should see an empty inbox.

### 2.3 Start The Webhook Receiver

Open another terminal:

```bash
node webhook-receiver.js
```

Verify it is running:

```bash
curl http://localhost:3001
```

Expected:

```json
{"status":"webhook receiver running","received":0}
```

## Step 3: Configure `.env`

Start from the example:

```bash
cp .env.example .env
```

Replace the contents of `.env` with the following. The only value you must change is `YOUR_OPENAI_API_KEY`:

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

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"},{"channel_account_id":"callback-demo","channel_kind":"webchat","mode":"fake"}]

PYTHON_CLAW_WORKER_POLL_SECONDS=2
PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30
```

### Key configuration points

- **`/usr/bin/python3`** is added to `NODE_RUNNER_ALLOWED_EXECUTABLES` so the node-runner permits Python execution.
- **`code-agent`** has its own policy profile (`code-policy`) with `remote_execution_enabled: true` and its own tool profile (`code-tools`) with `remote_exec` access.
- **`default-agent`** can delegate to all three child agents: `deploy-agent`, `code-agent`, and `notify-agent`. Its `max_active_delegations_per_session` is raised to `3`.
- `NODE_RUNNER_MODE=in_process` means the node-runner runs inside the gateway process. No separate Docker service needed.
- All auth tokens are set to readable demo values.

## Step 4: Install Dependencies and Run Migrations

```bash
uv sync --group dev
uv run alembic upgrade head
```

## Step 5: Start The Gateway

Open a new terminal:

```bash
uv run uvicorn apps.gateway.main:app --reload --host 0.0.0.0 --port 8000
```

## Step 6: Verify Health

```bash
curl http://localhost:8000/health/live
```

Expected:

```json
{"status":"ok"}
```

```bash
curl http://localhost:8000/health/ready -H 'Authorization: Bearer demo-operator-token'
```

Expected: a JSON response with `"status": "ok"` and dependency checks.

## Step 7: Send The Deployment Request (Webchat)

This is the user-facing interaction. Send a message through the webchat adapter:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "external_message_id": "msg-001",
    "sender_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Deploy the fake app northwind-api to staging. Use the deploy-agent. When deployment starts, post a start event to http://localhost:3001/deploy-events using remote_exec with curl. Do not report success until I send a deployment callback. Use correlation id northwind-api-staging-001."
  }'
```

Expected: `202 Accepted` with `session_id`, `run_id`, and `trace_id`.

Save the `session_id` from the response:

```bash
export SESSION_ID="<paste session_id from response>"
```

## Step 8: Process The Run (Worker)

In a new terminal, run the worker to process queued runs:

```bash
uv run python -c "from apps.worker.jobs import run_once; print(run_once())"
```

Run this command multiple times until it returns `None` (no more pending runs). Each invocation processes one queued run. You will need to run it several times as the parent agent delegates to deploy-agent, which also queues work.

Alternatively, run a simple polling loop:

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$(date +%H:%M:%S) $result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

## Step 9: Verify The Delegation And Webhook

Check the parent session:

```bash
curl -s http://localhost:8000/agents/default-agent/sessions \
  -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
```

Inspect delegations:

```bash
curl -s "http://localhost:8000/sessions/$SESSION_ID/delegations" \
  -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
```

You should see a child delegation targeting `deploy-agent`.

Check the terminal where `webhook-receiver.js` is running. You should see:

```
--- Webhook #1 received at 2026-03-29T... ---
Path: /deploy-events
Body: {"correlation_id":"northwind-api-staging-001","event":"deployment_started","app":"northwind-api","environment":"staging"}
---
```

## Step 10: Send The Completion Callback

Simulate the external deployment system calling back:

```bash
curl -X POST http://localhost:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "callback-demo",
    "external_message_id": "deploy-callback-001",
    "sender_id": "deployment-system",
    "peer_id": "northwind-api-staging-001",
    "content": "deployment_callback status=completed app=northwind-api environment=staging correlation_id=northwind-api-staging-001"
  }'
```

This creates a fresh inbound event through the gateway. It does not wake a sleeping process; it resumes the workflow from durable transcript state.

## Step 11: Request Code Generation

Now send a follow-up message asking the parent agent to generate a deploy report using the code-agent:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "external_message_id": "msg-002",
    "sender_id": "demo-user",
    "peer_id": "demo-user",
    "content": "The deployment callback arrived. Now delegate to code-agent to generate a Python deploy report script. The script should: 1) create a file called deploy_report.py that prints a JSON summary of the deployment (app=northwind-api, environment=staging, status=completed, correlation_id=northwind-api-staging-001, timestamp=now). 2) Execute the script and capture the output. Use remote_exec with python3 -c to write and run the code."
  }'
```

## Step 12: Process The Code Generation Runs

Run the worker again:

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$(date +%H:%M:%S) $result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

What happens during this phase:

1. The parent agent receives the message and delegates to `code-agent`.
2. `code-agent` proposes a `remote_exec` invocation with `python3 -c "{code}"`.
3. The approval gate fires — the user must approve the exact code before execution.
4. Once approved, the node-runner executes the Python code in the session workspace.
5. The script writes `deploy_report.py` and `deploy_report.json` to the workspace directory.
6. stdout/stderr from the script are captured and returned to `code-agent`.

### What the code-agent generates

The LLM will propose something like this for the `remote_exec` `code` argument:

```python
import json, datetime, pathlib

report = {
    "app": "northwind-api",
    "environment": "staging",
    "status": "completed",
    "correlation_id": "northwind-api-staging-001",
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z"
}

# Write the report as JSON
pathlib.Path("deploy_report.json").write_text(json.dumps(report, indent=2))

# Write a runnable script
script = '''import json, pathlib
report = json.loads(pathlib.Path("deploy_report.json").read_text())
print("=== Deployment Report ===")
for k, v in report.items():
    print(f"  {k}: {v}")
print("=========================")
'''
pathlib.Path("deploy_report.py").write_text(script)

# Execute immediately and print
exec(script)
```

The resulting argv sent to `subprocess.run()`:

```
["/usr/bin/python3", "-c", "<the code above>"]
```

### Verify the generated files

After the worker finishes, check the workspace directory:

```bash
ls -la .claw-sandboxes/sessions/code-agent/
```

You should see a directory named after the code-agent's session ID. Inside it:

```bash
# Find the session workspace (the session ID will vary)
find .claw-sandboxes/sessions/code-agent/ -type f
```

Expected files:

```
.claw-sandboxes/sessions/code-agent/<session-id>/deploy_report.py
.claw-sandboxes/sessions/code-agent/<session-id>/deploy_report.json
```

Inspect them:

```bash
# Read the generated JSON report
cat .claw-sandboxes/sessions/code-agent/*/deploy_report.json
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

```bash
# Read the generated Python script
cat .claw-sandboxes/sessions/code-agent/*/deploy_report.py
```

You can also run the generated script yourself:

```bash
cd .claw-sandboxes/sessions/code-agent/*/
python3 deploy_report.py
```

Expected:

```
=== Deployment Report ===
  app: northwind-api
  environment: staging
  status: completed
  correlation_id: northwind-api-staging-001
  generated_at: 2026-03-29T...
=========================
```

## Step 13: Request The Notification Fanout

Send a final message to trigger the email notification:

```bash
curl -X POST http://localhost:8000/providers/webchat/accounts/webchat-demo/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "external_message_id": "msg-003",
    "sender_id": "demo-user",
    "peer_id": "demo-user",
    "content": "Now delegate to notify-agent to send a deployment-complete notification email. Use remote_exec with curl to send SMTP to localhost:1025 via MailDev. Subject: Deployment complete northwind-api staging. Body: The deployment for northwind-api completed successfully. Correlation id northwind-api-staging-001."
  }'
```

## Step 14: Process The Notification Runs

```bash
while true; do
  result=$(uv run python -c "from apps.worker.jobs import run_once; r = run_once(); print(r or 'idle')")
  echo "$(date +%H:%M:%S) $result"
  if [ "$result" = "idle" ]; then break; fi
  sleep 2
done
```

## Step 15: Verify The Email In MailDev

Open [http://localhost:1080](http://localhost:1080) in your browser.

You should see a new email with:

- **Subject:** `Deployment complete northwind-api staging`
- **Body:** something like:

```text
The deployment for northwind-api completed successfully.
Correlation id: northwind-api-staging-001
```

If the notify-agent used `remote_exec` with `curl` to send email, the curl command would look like:

```bash
curl --url 'smtp://localhost:1025' \
  --mail-from 'python-claw@localhost' \
  --mail-rcpt 'ops-team@localhost' \
  --upload-file - <<EOF
From: python-claw@localhost
To: ops-team@localhost
Subject: Deployment complete northwind-api staging

The deployment for northwind-api completed successfully.
Correlation id: northwind-api-staging-001
EOF
```

MailDev captures any email sent to port 1025, regardless of the from/to addresses.

## Step 16: Inspect The Full Durable Record

Use the admin routes to inspect every step:

```bash
BASE=http://localhost:8000
AUTH='Authorization: Bearer demo-operator-token'

# Parent session
curl -s "$BASE/sessions/$SESSION_ID" -H "$AUTH" | python3 -m json.tool

# All messages in the session
curl -s "$BASE/sessions/$SESSION_ID/messages" -H "$AUTH" | python3 -m json.tool

# All runs in the session
curl -s "$BASE/sessions/$SESSION_ID/runs" -H "$AUTH" | python3 -m json.tool

# All delegations from the parent
curl -s "$BASE/sessions/$SESSION_ID/delegations" -H "$AUTH" | python3 -m json.tool

# Diagnostics: all runs across the system
curl -s "$BASE/diagnostics/runs" -H "$AUTH" | python3 -m json.tool

# Diagnostics: outbound deliveries
curl -s "$BASE/diagnostics/deliveries" -H "$AUTH" | python3 -m json.tool

# Diagnostics: node-runner execution audits
curl -s "$BASE/diagnostics/node-executions" -H "$AUTH" | python3 -m json.tool
```

What you should see in the audit trail:

- The webchat-originated parent session
- A child delegation for `deploy-agent` with a child session
- A `remote_exec` audit for the webhook POST (deploy-agent, `curl` to webhook receiver)
- The callback-triggered inbound message and run
- A child delegation for `code-agent` with a child session
- A `remote_exec` audit for the Python execution (code-agent, `python3 -c`)
- A child delegation for `notify-agent` with a child session
- A `remote_exec` audit for the email send (notify-agent, `curl` to MailDev SMTP)
- Outbound delivery records for webchat responses

## Step 17: Poll For Webchat Responses

The webchat adapter supports polling for assistant responses. To see what the assistant said at each stage:

```bash
curl -s "http://localhost:8000/providers/webchat/accounts/webchat-demo/poll?stream_id=demo-user&limit=50" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' | python3 -m json.tool
```

This returns all outbound deliveries for the webchat session, showing the assistant's responses at each stage of the deployment, code generation, and notification flow.

## What This Demo Proves

| Capability | How it is demonstrated |
|-----------|----------------------|
| Gateway-first routing | All messages enter through `/providers/webchat/.../messages` or `/inbound/message` |
| Durable sessions | Session persists across multiple runs and follow-up messages; inspect via admin API |
| Async worker execution | Worker processes runs independently of the gateway |
| Provider-backed LLM | OpenAI gpt-4o-mini drives the assistant decisions |
| Sub-agent delegation | `default-agent` delegates to three specialist agents: `deploy-agent`, `code-agent`, `notify-agent` |
| Remote execution (curl) | Node-runner executes approved `curl` commands for webhook and email |
| Remote execution (python3) | Node-runner executes approved `python3 -c` commands for code generation |
| Code generation | `code-agent` writes Python files to an isolated per-session workspace |
| Workspace isolation | Generated files persist in `.claw-sandboxes/sessions/code-agent/<session-id>/` |
| Callback re-entry | External callback resumes workflow via a new inbound event |
| Approval governance | `remote_exec` invocations require explicit user approval before execution |
| Production auth | Admin routes require bearer token; unauthenticated requests are rejected |
| Rate limiting | Quota enforcement is active on all inbound routes |
| Observability | Every step is auditable through diagnostics APIs and node-execution audit records |

## Troubleshooting

### Worker returns `None` immediately

The run may still be in `queued` state waiting for a previous run to finish. Check:

```bash
curl -s http://localhost:8000/diagnostics/runs -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
```

Look for runs with `status: "queued"` or `status: "claimed"`.

### No files in .claw-sandboxes

1. Verify `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES` includes `/usr/bin/python3`
2. Check the node-execution audits for the code-agent's `remote_exec` result:
   ```bash
   curl -s http://localhost:8000/diagnostics/node-executions -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
   ```
3. Look for `deny_reason` in the audit if execution was blocked
4. Verify the `python3` path on your system: `which python3`

### python3 is at a different path

On some systems, `python3` may be at `/usr/local/bin/python3` or another location. Check:

```bash
which python3
```

Update `PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES` to include the correct path. The `code-agent`'s command template must also use the matching path.

### MailDev shows no email

1. Verify MailDev is running: `curl http://localhost:1080`
2. Verify curl can send SMTP: `curl --url 'smtp://localhost:1025' --mail-from 'test@test' --mail-rcpt 'test@test' -T - <<< "Subject: test"`
3. Check the node-execution audits for errors in the `remote_exec` call

### Webhook receiver shows no requests

1. Verify it is running: `curl http://localhost:3001`
2. Check node-execution audits for the deploy-agent's `remote_exec` result

### LLM does not delegate or generate code

The LLM may not follow the delegation instruction precisely. Check the session messages to see what the assistant decided:

```bash
curl -s "http://localhost:8000/sessions/$SESSION_ID/messages" \
  -H 'Authorization: Bearer demo-operator-token' | python3 -m json.tool
```

If needed, send a follow-up message reinforcing the delegation request. For code generation, being specific about the expected output format helps the LLM produce correct `remote_exec` arguments.

## Cleanup

Stop all services:

```bash
# Stop MailDev (Ctrl+C in its terminal)
# Stop webhook receiver (Ctrl+C in its terminal)
# Stop gateway (Ctrl+C in its terminal)

# Stop Docker infrastructure
docker compose --env-file .env down

# Remove generated workspace files
rm -rf .claw-sandboxes/

# Remove volumes if you want a fresh start
docker compose --env-file .env down -v
```

## Extending This Example

### More Ambitious Code Generation

The code-agent is not limited to simple report scripts. Some ideas:

- Generate a data validation script that checks deployment health endpoints
- Create a CSV or HTML report from structured deployment data
- Write a test script that verifies the deployed app responds correctly
- Generate configuration files (YAML, TOML) for the deployed service

Each execution goes through the same approval gate, so the user always sees and approves the exact code before it runs.

### Two-Step Write-Then-Execute Pattern

For more complex scripts, use two separate `remote_exec` invocations:

1. **First call** with `python3 -c "{code}"` — writes a `.py` file to the workspace
2. **Second call** with a different template: `python3 {script_path}` — executes the file

This needs two approved command templates. The second template would look like:

```python
NodeCommandTemplate(
    executable="/usr/bin/python3",
    argv_template=["{script_path}"],
    workspace_binding_kind="session",
    workspace_mount_mode="read_write",
    timeout_seconds=15,
)
```

### Add Real Slack Notifications

To add real Slack output alongside the local demo:

1. Create a Slack app and enable Incoming Webhooks
2. Add the webhook URL as a second `remote_exec` template for `notify-agent`
3. The node-runner will POST to both MailDev and Slack

### Add Telegram As An Ingress Channel

1. Create a Telegram bot via `@BotFather`
2. Add the bot token to `PYTHON_CLAW_CHANNEL_ACCOUNTS`
3. Expose your gateway publicly (e.g., via `ngrok http 8000`)
4. Set the Telegram webhook: `curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" -d '{"url":"https://<ngrok-url>/providers/telegram/webhook/<account-id>"}'`

### Replace MailDev With Mailpit

If you prefer a Go-based alternative with a REST API:

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
```

Web UI at [http://localhost:8025](http://localhost:8025). Same SMTP on port 1025.

### Use n8n For Complex Automations

For workflows beyond simple notifications:

```bash
npx n8n start
```

Web UI at [http://localhost:5678](http://localhost:5678). Create webhook-triggered workflows that python-claw's `remote_exec` can call.
