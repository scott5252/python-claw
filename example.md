# Example: Telegram Deployment Orchestration With Slack, Gmail, webhook.site, curl Callback, and Docker

This guide gives you a realistic `python-claw` reference example based on the current codebase and the behavior described in Specs `001` through `017`, especially:

- gateway-first inbound routing and durable sessions
- async worker-owned execution runs
- provider-backed tool use
- durable sub-agent delegation
- production channel adapters for Telegram and Slack
- remote execution through the node-runner
- production hardening around auth, diagnostics, and quotas

It is designed to showcase this scenario:

1. A user asks in Telegram to deploy a made-up app.
2. The primary assistant delegates the deployment work to a deployment sub-agent.
3. The deployment sub-agent calls a test endpoint on `webhook.site`.
4. A user sends a `curl` callback back into `python-claw` when the deployment is complete.
5. The workflow resumes and sends completion notifications to Slack and Gmail.

## Important Reality Check

This example is faithful to the current repository, but two parts use bridge patterns because they are not native first-class adapters in this codebase yet:

- Telegram is a native adapter in this repo.
- Slack is a native adapter in this repo, but for this deployment-notification example the easiest path is a Slack Incoming Webhook invoked through `remote_exec`.
- Gmail is not a native adapter in this repo today, so this example uses a small Gmail bridge endpoint implemented as a Google Apps Script web app.

Also note:

- `python-claw` already supports durable delegation, but it does not currently have a built-in "sleep until arbitrary external callback arrives inside the same child run" primitive.
- The realistic pattern in this codebase is event-driven re-entry: the callback comes back through the gateway as a new inbound event, and the next run resumes the workflow from durable transcript state.

That still demonstrates the right platform behavior:

- durable sessions
- durable child sessions
- worker-owned async execution
- callback-driven continuation
- cross-system notification fanout

## Architecture For This Example

Use this operating model:

- Telegram is the user-facing ingress channel.
- The parent assistant is `default-agent`.
- The first child is `deploy-agent`.
- The second child is `notify-agent`.
- `deploy-agent` uses `remote_exec` to:
  - POST a "deployment started" event to `webhook.site`
  - optionally call a fake deployment system endpoint
- the user later sends a `curl` callback to `python-claw` through `POST /inbound/message`
- that callback re-enters the durable parent session
- the parent assistant delegates a bounded notification task to `notify-agent`
- `notify-agent` uses `remote_exec` to:
  - POST to a Slack Incoming Webhook
  - POST to a Gmail bridge endpoint

## Files Added For This Example

This repo now includes three helper files to make the Docker part concrete:

- [Dockerfile](/Users/scottcornell/src/my-projects/python-claw/Dockerfile)
- [docker-compose.app.yml](/Users/scottcornell/src/my-projects/python-claw/docker-compose.app.yml)
- [worker_loop.py](/Users/scottcornell/src/my-projects/python-claw/scripts/worker_loop.py)

They let you run:

- the gateway in Docker
- the worker in Docker
- the node-runner in Docker

## Step 1: Create `.env`

Start from:

```bash
cp .env.example .env
```

Then replace the contents you need with the following working example values.

Use your real secrets where marked:

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
PYTHON_CLAW_NODE_RUNNER_SIGNING_KEY_ID=deploy-demo-key
PYTHON_CLAW_NODE_RUNNER_SIGNING_SECRET=deploy-demo-signing-secret
PYTHON_CLAW_NODE_RUNNER_INTERNAL_BEARER_TOKEN=deploy-demo-node-token
PYTHON_CLAW_NODE_RUNNER_REQUEST_TTL_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_TIMEOUT_CEILING_SECONDS=30
PYTHON_CLAW_NODE_RUNNER_ALLOWED_EXECUTABLES=/usr/bin/curl,/bin/echo,/usr/bin/env
PYTHON_CLAW_NODE_RUNNER_ALLOW_OFF_MODE=false

PYTHON_CLAW_ADMIN_READS_REQUIRE_AUTH=true
PYTHON_CLAW_DIAGNOSTICS_REQUIRE_AUTH=true
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true
PYTHON_CLAW_AUTH_FAIL_CLOSED_IN_PRODUCTION=true
PYTHON_CLAW_OPERATOR_AUTH_BEARER_TOKEN=change-me
PYTHON_CLAW_INTERNAL_SERVICE_AUTH_TOKEN=change-me-internal
PYTHON_CLAW_OPERATOR_PRINCIPAL_HEADER_NAME=X-Operator-Id
PYTHON_CLAW_INTERNAL_SERVICE_PRINCIPAL_HEADER_NAME=X-Internal-Service-Principal
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal

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

PYTHON_CLAW_POLICY_PROFILES=[{"key":"default","remote_execution_enabled":false,"denied_capability_names":[],"delegation_enabled":true,"max_delegation_depth":2,"allowed_child_agent_ids":["deploy-agent"],"max_active_delegations_per_run":1,"max_active_delegations_per_session":2},{"key":"deploy-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":true,"max_delegation_depth":2,"allowed_child_agent_ids":["notify-agent"],"max_active_delegations_per_run":1,"max_active_delegations_per_session":2},{"key":"notify-policy","remote_execution_enabled":true,"denied_capability_names":[],"delegation_enabled":false,"max_delegation_depth":0,"allowed_child_agent_ids":[],"max_active_delegations_per_run":null,"max_active_delegations_per_session":null}]

PYTHON_CLAW_TOOL_PROFILES=[{"key":"default","allowed_capability_names":["echo_text","delegate_to_agent"]},{"key":"deploy-tools","allowed_capability_names":["echo_text","delegate_to_agent","remote_exec"]},{"key":"notify-tools","allowed_capability_names":["echo_text","remote_exec"]}]

PYTHON_CLAW_HISTORICAL_AGENT_PROFILE_OVERRIDES=[{"agent_id":"deploy-agent","model_profile_key":"default","policy_profile_key":"deploy-policy","tool_profile_key":"deploy-tools"},{"agent_id":"notify-agent","model_profile_key":"default","policy_profile_key":"notify-policy","tool_profile_key":"notify-tools"}]

PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"telegram-prod","channel_kind":"telegram","mode":"real","outbound_token":"YOUR_TELEGRAM_BOT_TOKEN","webhook_secret":"YOUR_TELEGRAM_WEBHOOK_SECRET"},{"channel_account_id":"slack-prod","channel_kind":"slack","mode":"real","outbound_token":"YOUR_SLACK_BOT_TOKEN","signing_secret":"YOUR_SLACK_SIGNING_SECRET"},{"channel_account_id":"webchat-demo","channel_kind":"webchat","mode":"fake"},{"channel_account_id":"callback-demo","channel_kind":"webchat","mode":"fake"}]

PYTHON_CLAW_WORKER_POLL_SECONDS=2
PYTHON_CLAW_WORKER_IDLE_LOG_EVERY=30
```

## Step 2: Gather The External Values You Need

Before you start Docker, collect these values:

- `YOUR_OPENAI_API_KEY`
- `YOUR_TELEGRAM_BOT_TOKEN`
- `YOUR_TELEGRAM_WEBHOOK_SECRET`
- `YOUR_SLACK_BOT_TOKEN`
- `YOUR_SLACK_SIGNING_SECRET`
- `YOUR_SLACK_INCOMING_WEBHOOK_URL`
- `YOUR_WEBHOOK_SITE_URL`
- `YOUR_GMAIL_BRIDGE_URL`
- `YOUR_GMAIL_BRIDGE_SECRET`

The last four are not read directly by `python-claw` settings in this example. They are the values you will bake into approved `remote_exec` command templates and test payloads.

## Step 3: Telegram Setup

### 3.1 Create the bot

1. Open Telegram and start a chat with `@BotFather`.
2. Run `/newbot`.
3. Choose a display name and bot username.
4. Copy the bot token.
5. Put that token into `PYTHON_CLAW_CHANNEL_ACCOUNTS` as `outbound_token` for `telegram-prod`.

### 3.2 Create the webhook secret

1. Generate any long random string.
2. Put it into `PYTHON_CLAW_CHANNEL_ACCOUNTS` as `webhook_secret` for `telegram-prod`.

### 3.3 Set the Telegram webhook

After Docker is running and your gateway is reachable from the internet, run:

```bash
curl -X POST "https://api.telegram.org/botYOUR_TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://YOUR_PUBLIC_HOST/providers/telegram/webhook/telegram-prod",
    "secret_token": "YOUR_TELEGRAM_WEBHOOK_SECRET"
  }'
```

### 3.4 Verify the probe route

```bash
curl http://127.0.0.1:8000/providers/telegram/webhook/telegram-prod
```

Expected result:

```json
{"status":"ok"}
```

## Step 4: Slack Setup

This example uses Slack in two ways:

- native Slack adapter setup for the platform
- Slack Incoming Webhook for the deployment-complete notification fanout

### 4.1 Create the Slack app

1. Open `https://api.slack.com/apps`.
2. Create a new app.
3. Enable a bot user.
4. Install the app to your workspace.
5. Copy the bot token.
6. Copy the signing secret.
7. Put them into the `slack-prod` entry in `PYTHON_CLAW_CHANNEL_ACCOUNTS`.

### 4.2 Create a Slack Incoming Webhook

1. In the same Slack app, enable Incoming Webhooks.
2. Add a webhook for the target channel such as `#deployments`.
3. Copy the webhook URL.
4. Save it as `YOUR_SLACK_INCOMING_WEBHOOK_URL`.

### 4.3 Optional native event webhook

If you also want native Slack ingress to work:

1. Enable Event Subscriptions.
2. Set the request URL to:

```text
https://YOUR_PUBLIC_HOST/providers/slack/events
```

3. Subscribe to message events that fit your workspace.

For this example, Slack ingress is optional. The important Slack output path is the Incoming Webhook used by `notify-agent`.

## Step 5: Gmail Setup

`python-claw` does not have a first-class Gmail adapter today, so use a Gmail bridge. The easiest bridge for a demo is a Google Apps Script web app that sends mail from your Gmail account.

### 5.1 Create the Apps Script

1. Open `https://script.google.com`.
2. Create a new project named `python-claw-gmail-bridge`.
3. Replace the default code with this:

```javascript
function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  const expectedSecret = PropertiesService.getScriptProperties().getProperty("BRIDGE_SECRET");
  if (!body.secret || body.secret !== expectedSecret) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, error: "unauthorized" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  GmailApp.sendEmail(
    body.to,
    body.subject,
    body.text
  );

  return ContentService.createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
```

### 5.2 Configure the shared secret

1. In Apps Script, open Project Settings.
2. Add Script Property:
   - key: `BRIDGE_SECRET`
   - value: your chosen shared secret
3. Save it as `YOUR_GMAIL_BRIDGE_SECRET`.

### 5.3 Deploy the web app

1. Click Deploy.
2. Choose New deployment.
3. Select Web app.
4. Execute as yourself.
5. Allow access as appropriate for your environment.
6. Copy the deployment URL.
7. Save it as `YOUR_GMAIL_BRIDGE_URL`.

## Step 6: webhook.site Setup

1. Open `https://webhook.site`.
2. Create a fresh temporary endpoint.
3. Copy the unique URL.
4. Save it as `YOUR_WEBHOOK_SITE_URL`.

This endpoint is where `deploy-agent` will send its fake deployment start event.

## Step 7: Start Everything In Docker

From the repo root run:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml up -d --build
```

Check status:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml ps
```

You should see:

- `postgres`
- `redis`
- `gateway`
- `worker`
- `node-runner`

## Step 8: Run Migrations

Run:

```bash
docker compose --env-file .env -f docker-compose.yml -f docker-compose.app.yml run --rm gateway uv run alembic upgrade head
```

## Step 9: Verify Health

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready -H 'Authorization: Bearer change-me'
```

## Step 10: Seed The Remote Execution Capabilities

For this example, `deploy-agent` and `notify-agent` need approved `remote_exec` command templates. This is the cleanest way to stay inside the current code structure because:

- `remote_exec` already exists
- execution goes through the node-runner
- approval and audit records are already part of the platform

You need three approved command templates:

1. `curl` to `webhook.site`
2. `curl` to Slack Incoming Webhook
3. `curl` to the Gmail bridge

Use the same seeding pattern shown in the remote execution sections of the earlier demos. The template shape should be a `curl` command with scalar argument slots only.

Recommended templates:

- deployment start notifier
- Slack deploy-complete notifier
- Gmail deploy-complete notifier

Keep the approved commands narrowly scoped to exact URLs and exact JSON shapes for the demo.

## Step 11: Telegram Prompt For The Parent Agent

Send this message to your Telegram bot:

```text
Deploy the fake app northwind-api to staging.
Use the deploy-agent.
When deployment starts, post a start event to the approved webhook.site endpoint.
Do not report success until I send a deployment callback.
When the callback says completed, delegate to notify-agent to notify Slack and Gmail.
Use correlation id northwind-api-staging-001.
```

What should happen conceptually:

1. Telegram webhook sends the inbound event to `python-claw`.
2. The gateway creates or reuses the session.
3. The worker processes the queued run.
4. The parent assistant delegates to `deploy-agent`.

## Step 12: Verify The Delegation

Use the admin routes:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'

curl -s $BASE/agents/default-agent/sessions -H "$AUTH"
```

Then inspect the parent session messages:

```bash
curl -s $BASE/sessions/YOUR_SESSION_ID/messages -H "$AUTH"
```

Then inspect delegations:

```bash
curl -s $BASE/sessions/YOUR_SESSION_ID/delegations -H "$AUTH"
```

You should see a child delegation targeting `deploy-agent`.

## Step 13: Confirm The webhook.site Call

Once `deploy-agent` runs and its approved `remote_exec` succeeds, check your `webhook.site` page.

You should see a POST that includes a correlation id like:

```text
northwind-api-staging-001
```

## Step 14: Send The Completion Callback With `curl`

This is the callback that re-enters the app through the gateway and tells the system the deployment is complete.

Run:

```bash
curl -X POST http://127.0.0.1:8000/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "callback-demo",
    "external_message_id": "deploy-callback-northwind-api-staging-001",
    "sender_id": "deployment-system",
    "peer_id": "northwind-api-staging-001",
    "content": "deployment_callback status=completed app=northwind-api environment=staging correlation_id=northwind-api-staging-001"
  }'
```

Important note:

- this callback creates a fresh inbound event, which is the correct gateway-first pattern in this codebase
- it does not "wake a sleeping child process"
- instead it resumes the workflow from durable transcript state

## Step 15: Trigger The Notification Fanout

After the callback arrives, the next run should:

1. interpret the callback as deployment completion
2. delegate a bounded notification task to `notify-agent`
3. have `notify-agent` call:
   - Slack Incoming Webhook
   - Gmail bridge

Recommended notification payload:

- Slack text:

```text
Deployment complete: northwind-api is now live in staging. Correlation id northwind-api-staging-001.
```

- Gmail subject:

```text
Deployment complete: northwind-api staging
```

- Gmail body:

```text
The staged deployment for northwind-api completed successfully.
Correlation id: northwind-api-staging-001
Triggered from Telegram via python-claw.
```

## Step 16: Verify Slack And Gmail

Verify Slack:

- open the Slack channel tied to your Incoming Webhook
- confirm the deployment-complete message arrived

Verify Gmail:

- check the inbox of the recipient used by the Gmail bridge payload
- confirm the deployment-complete email arrived

## Step 17: Inspect The Durable Records

Use these routes to inspect the flow:

```bash
curl -s $BASE/sessions/YOUR_SESSION_ID -H "$AUTH"
curl -s $BASE/sessions/YOUR_SESSION_ID/messages -H "$AUTH"
curl -s $BASE/sessions/YOUR_SESSION_ID/runs -H "$AUTH"
curl -s $BASE/sessions/YOUR_SESSION_ID/delegations -H "$AUTH"
curl -s $BASE/diagnostics/runs -H "$AUTH"
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
curl -s $BASE/diagnostics/node-executions -H "$AUTH"
```

What you should see:

- the Telegram-originated parent session
- a child delegation for `deploy-agent`
- a callback-triggered inbound run
- a second child delegation for `notify-agent`
- node-runner execution audits for the approved `curl` commands

## Recommended Operator Notes

This is the cleanest way to describe the example to stakeholders:

- Telegram is the human-facing chat channel.
- `python-claw` owns durable session state and async runs.
- deployment kickoff is delegated to a bounded specialist child agent.
- external completion returns through a gateway webhook instead of an in-memory callback.
- Slack and Gmail notifications are executed through auditable approved node-runner actions.

## What Is Native vs Bridged In This Example

Native in this repo today:

- gateway-first inbound routing
- Telegram adapter
- Slack adapter
- delegation and child sessions
- worker-owned async execution
- node-runner remote execution
- operator diagnostics

Bridge pattern used in this example:

- Gmail notification via Google Apps Script
- Slack deployment notification via Incoming Webhook
- callback re-entry via generic `/inbound/message`

## Known Limitations

- Gmail is not a built-in channel adapter yet.
- Cross-channel proactive fanout is best done here through approved `remote_exec`, not `send_message`, because `send_message` is session-channel-bound in the current code.
- The exact "child agent waits for external callback in the same run" pattern is not implemented yet. The correct current pattern is callback-driven re-entry through a new inbound event.
- For `remote_exec`, exact approvals matter. Keep the approved command templates tight and demo-specific.

## Suggested Next Improvement If You Want This To Become Productized

The next practical enhancement would be a first-class outbound webhook tool or notification connector layer that can:

- target Slack, Gmail, and other systems without going through raw `curl`
- keep cross-channel delivery inside the same typed runtime contract as `send_message`
- model callback correlation ids as first-class workflow state instead of transcript conventions
