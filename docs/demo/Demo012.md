# Demo Guide: Spec 012 Production Channel Integration

This guide shows developers and non-developers how to run a realistic local demo of the new production channel features from Spec 012.

The demo covers:

1. verified provider-facing inbound routes for Slack and Telegram
2. production-style webchat inbound plus durable polling for outbound replies
3. the shared gateway-first acceptance path through `SessionService.process_inbound(...)`
4. worker-owned outbound dispatch through the channel adapter layer
5. dedupe behavior for provider retries and redelivery
6. durable delivery records and polling-visible outbound results

The demo uses one simple business story:

- a neighborhood bike shop now supports customers through its website chat, Slack support inbox, and Telegram bot

Important note about this demo:

- the default local demo uses fake channel accounts so you can run everything without live Slack or Telegram credentials
- the gateway and worker still execute the real backend workflow
- Slack and Telegram inbound requests still go through the new provider-specific verification and translation routes
- production webchat uses authenticated HTTP inbound plus authenticated polling, not streaming
- an optional final section explains how to swap one or more accounts to `real` mode later

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands that simulate Slack, Telegram, and webchat traffic

You do not need live provider credentials for the main demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime

Work from the project root:

```bash
cd /Users/scottcornell/src/my-projects/python-claw
```

## 3. Setup The Application

### Step 1: Prepare `.env`

If `.env` does not exist yet:

```bash
cp .env.example .env
```

For this demo, make sure these values exist in `.env`:

```text
PYTHON_CLAW_DATABASE_URL=postgresql+psycopg://openassistant:openassistant@localhost:5432/openassistant
PYTHON_CLAW_DIAGNOSTICS_ADMIN_BEARER_TOKEN=change-me
PYTHON_CLAW_DIAGNOSTICS_INTERNAL_SERVICE_TOKEN=change-me-internal
PYTHON_CLAW_HEALTH_READY_REQUIRES_AUTH=true

PYTHON_CLAW_RUNTIME_MODE=rule_based
PYTHON_CLAW_RUNTIME_TRANSCRIPT_CONTEXT_LIMIT=20

PYTHON_CLAW_CHANNEL_ACCOUNTS=[
  {"channel_account_id":"acct","channel_kind":"slack","mode":"fake"},
  {"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},
  {"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"slack","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"telegram","mode":"fake"},
  {"channel_account_id":"acct-1","channel_kind":"webchat","mode":"fake"}
]
```

Important formatting note:

- `PYTHON_CLAW_CHANNEL_ACCOUNTS` must be valid JSON
- do not wrap the whole JSON value in extra single quotes
- safest option: keep it on one line exactly as valid JSON

Good example:

```text
PYTHON_CLAW_CHANNEL_ACCOUNTS=[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"}]
```

Bad example:

```text
PYTHON_CLAW_CHANNEL_ACCOUNTS='[{"channel_account_id":"acct","channel_kind":"slack","mode":"fake"}]'
```

If you use the bad form, commands like `uv run alembic upgrade head` can fail because the settings loader will try to parse the leading single quote as JSON.

What this means:

- `rule_based` keeps the demo easy to run locally
- the new typed channel-account registry is active
- all three supported channels resolve through the same registry contract
- `fake` mode lets you exercise the full backend flow without real provider tokens

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

### Step 3: Start local infrastructure

Run:

```bash
docker compose --env-file .env up -d
```

Optional checks:

```bash
docker compose ps
docker compose logs postgres
```

### Step 4: Apply database migrations

Run:

```bash
uv run alembic upgrade head
```

This is important for Spec 012 because the new migration adds:

- session transport-address persistence
- bounded outbound provider metadata
- richer outbound attempt metadata

## 4. Run The Application

Use three terminals for the demo.

### Terminal A: Start the gateway

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

The gateway starts on `http://127.0.0.1:8000`.

### Terminal B: Keep the worker helper ready

Run this command each time the guide tells you to process queued work:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Terminal C: Use `curl`

Set these shell variables once:

```bash
BASE=http://127.0.0.1:8000
AUTH='Authorization: Bearer change-me'
```

Verify the service:

```bash
curl $BASE/health/live
curl $BASE/health/ready -H "$AUTH"
```

## 5. Variables You Will Reuse

Write these down as you go:

- `WEBCHAT_SESSION_ID`
- `WEBCHAT_RUN_ID`
- `WEBCHAT_STREAM_ID`
- `SLACK_SESSION_ID`
- `TELEGRAM_SESSION_ID`

Whenever a later step says “reuse the earlier variable,” copy the real value you captured in that earlier step.

## 6. Main Demo A: Website Chat End To End

This is the easiest full end-to-end demo for mixed technical and non-technical audiences because it shows:

- authenticated webchat inbound
- normal gateway acceptance
- worker-owned assistant execution
- outbound dispatch
- browser-style polling for completed replies

### Scenario

A customer opens the bike shop website and asks whether tune-ups are available this afternoon.

### Step 1: Submit a webchat message

In Terminal C, run:

```bash
curl -s $BASE/providers/webchat/accounts/acct/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "customer-riley",
    "content": "Hi, can I bring in my bike for a tune-up after 3 PM today?",
    "peer_id": "customer-riley",
    "stream_id": "webchat-stream-riley-001",
    "message_id": "webchat-msg-001"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON containing `session_id`, `message_id`, `run_id`, `status`, `dedupe_status`, `trace_id`, and `external_message_id`

Write down:

- `WEBCHAT_SESSION_ID`
  Use the returned `session_id`
- `WEBCHAT_RUN_ID`
  Use the returned `run_id`
- `WEBCHAT_STREAM_ID`
  Use `webchat-stream-riley-001`

Important reuse note:

- you will reuse `WEBCHAT_SESSION_ID` in Step 4
- you will reuse `WEBCHAT_STREAM_ID` in Steps 3 and 5

What is happening in the system:

1. the dedicated webchat route authenticates the client token
2. the route translates the request into the canonical inbound shape
3. the gateway persists transcript state and queues one run
4. the session stores a durable transport address for future outbound delivery and polling

### Step 2: Process the queued run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

Expected result:

- the command prints a run id
- it should match or include the run created in Step 1

What is happening:

1. the worker claims the queued run
2. the assistant produces a reply
3. the dispatcher creates outbound delivery rows
4. the webchat adapter records whole-message delivery state for polling

### Step 3: Poll for the outbound reply

In Terminal C, run:

```bash
curl -s "$BASE/providers/webchat/accounts/acct/poll?stream_id=webchat-stream-riley-001" \
  -H 'X-Webchat-Client-Token: fake-webchat-token'
```

Expected result:

- HTTP `200`
- JSON with `items`
- at least one item should contain:
  - `delivery_id`
  - `status`
  - `delivery_kind`
  - `provider_message_id`
  - `payload`

You should see the assistant reply inside `payload.text`.

Write down:

- `WEBCHAT_LAST_DELIVERY_ID`
  Use the `delivery_id` from the newest item

Important reuse note:

- you will reuse `WEBCHAT_LAST_DELIVERY_ID` in Step 5

### Step 4: Confirm the canonical transcript for the same session

Replace `replace-with-webchat-session-id` with your real `WEBCHAT_SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-webchat-session-id/messages"
```

Expected result:

- the session shows the user message and the assistant message
- this proves transcript rows remain canonical
- the polling result is an operational delivery projection, not a second transcript

### Step 5: Prove polling is cursor-safe

Replace `replace-with-last-delivery-id` with your real `WEBCHAT_LAST_DELIVERY_ID`, then run:

```bash
curl -s "$BASE/providers/webchat/accounts/acct/poll?stream_id=webchat-stream-riley-001&after_delivery_id=replace-with-last-delivery-id" \
  -H 'X-Webchat-Client-Token: fake-webchat-token'
```

Expected result:

- `items` should now be empty unless a newer delivery exists

This demonstrates:

- polling is replay-safe
- the response cursor is monotonic
- only already-persisted outbound delivery results are returned

## 7. Main Demo B: Slack Provider Ingress And Dedupe

This section demonstrates the new verified Slack ingress route and duplicate suppression.

### Scenario

The bike shop’s Slack support channel receives the same webhook twice because Slack retries delivery after a network timeout.

### Step 1: Generate a signed Slack request

In Terminal C, run this helper exactly as written:

```bash
python - <<'PY'
import hashlib
import hmac
import json

payload = {
    "type": "event_callback",
    "api_app_id": "acct",
    "event": {
        "type": "message",
        "channel": "C-BIKE-SUPPORT",
        "channel_type": "channel",
        "user": "U-CUSTOMER-01",
        "text": "Do you have same-day flat repair service?",
        "ts": "1710000000.000100"
    }
}
body = json.dumps(payload, separators=(",", ":"))
timestamp = "1710000000"
secret = "fake-slack-secret"
signature = "v0=" + hmac.new(
    secret.encode("utf-8"),
    f"v0:{timestamp}:{body}".encode("utf-8"),
    hashlib.sha256,
).hexdigest()

print("SLACK_BODY=" + body)
print("SLACK_TIMESTAMP=" + timestamp)
print("SLACK_SIGNATURE=" + signature)
PY
```

Copy the printed values into your shell:

- `SLACK_BODY`
- `SLACK_TIMESTAMP`
- `SLACK_SIGNATURE`

Important reuse note:

- you will reuse all three values in Steps 2 and 3

### Step 2: Send the first Slack webhook

Run:

```bash
curl -s $BASE/providers/slack/events \
  -H 'Content-Type: application/json' \
  -H "X-Slack-Request-Timestamp: $SLACK_TIMESTAMP" \
  -H "X-Slack-Signature: $SLACK_SIGNATURE" \
  -d "$SLACK_BODY"
```

Expected result:

- HTTP `202`
- `dedupe_status` should be `accepted`

Write down:

- `SLACK_SESSION_ID`
  Use the returned `session_id`

### Step 3: Replay the same Slack webhook

Run the exact same command again:

```bash
curl -s $BASE/providers/slack/events \
  -H 'Content-Type: application/json' \
  -H "X-Slack-Request-Timestamp: $SLACK_TIMESTAMP" \
  -H "X-Slack-Signature: $SLACK_SIGNATURE" \
  -d "$SLACK_BODY"
```

Expected result:

- HTTP `202`
- `dedupe_status` should now be `duplicate`
- `session_id`, `message_id`, and `run_id` should match the first response

This demonstrates the spec 012 dedupe rule:

- Slack dedupe uses the canonical external identity derived from conversation id plus message timestamp

### Step 4: Process the Slack run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Step 5: Inspect the Slack session

Replace `replace-with-slack-session-id` with your real `SLACK_SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-slack-session-id/messages"
```

Expected result:

- the session contains one user message from Slack
- the assistant reply is present after the worker runs

### Step 6: Inspect delivery diagnostics

Run:

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Expected result:

- you should see outbound delivery items
- delivery rows now include bounded provider metadata and payload previews

## 8. Main Demo C: Telegram Provider Ingress

This section demonstrates the Telegram webhook route and its verified translation path.

### Scenario

A customer uses the bike shop Telegram bot to ask whether Saturday appointments are open.

### Step 1: Send a Telegram webhook update

In Terminal C, run:

```bash
curl -s $BASE/providers/telegram/webhook/acct \
  -H 'Content-Type: application/json' \
  -H 'X-Telegram-Bot-Api-Secret-Token: fake-telegram-secret' \
  -d '{
    "update_id": 900001,
    "message": {
      "message_id": 42,
      "text": "Are Saturday appointments available for a brake check?",
      "chat": {
        "id": 555123,
        "type": "private"
      },
      "from": {
        "id": 777001,
        "is_bot": false,
        "first_name": "Dana"
      }
    }
  }'
```

Expected result:

- HTTP `202`
- JSON with `session_id`, `run_id`, and `dedupe_status=accepted`

Write down:

- `TELEGRAM_SESSION_ID`
  Use the returned `session_id`

### Step 2: Process the Telegram run

In Terminal B, run:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Step 3: Read back the Telegram session

Replace `replace-with-telegram-session-id` with your real `TELEGRAM_SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-telegram-session-id/messages"
```

Expected result:

- the user message and assistant reply are present

### Step 4: Show ignored unsupported Telegram updates

Run:

```bash
curl -s $BASE/providers/telegram/webhook/acct \
  -H 'Content-Type: application/json' \
  -H 'X-Telegram-Bot-Api-Secret-Token: fake-telegram-secret' \
  -d '{
    "update_id": 900002,
    "edited_message": {
      "message_id": 43
    }
  }'
```

Expected result:

- HTTP `200`
- JSON showing `status=ignored`

This demonstrates that unsupported provider event types are ignored instead of becoming transcript rows.

## 9. Operator Verification Steps

These checks help technical audiences prove the backend is using the new transport-aware contracts correctly.

### Step 1: Inspect one session record

Replace `replace-with-webchat-session-id` with your real `WEBCHAT_SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-webchat-session-id"
```

Expected result:

- the session belongs to `channel_kind=webchat`
- the session exists independently of the polling API

### Step 2: Inspect delivery diagnostics again

Run:

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Look for:

- `channel_kind`
- `provider_message_id`
- `provider_metadata`
- `payload`
- `failure_category` when applicable

### Step 3: Prove a bad Slack signature fails closed

Run:

```bash
curl -i $BASE/providers/slack/events \
  -H 'Content-Type: application/json' \
  -H 'X-Slack-Request-Timestamp: 1710000000' \
  -H 'X-Slack-Signature: v0=bad-signature' \
  -d '{"type":"event_callback","api_app_id":"acct","event":{"type":"message","channel":"C-BIKE-SUPPORT","channel_type":"channel","user":"U-CUSTOMER-01","text":"bad request","ts":"1710000000.000200"}}'
```

Expected result:

- HTTP `401 Unauthorized`

This proves unverified provider requests fail closed before transcript writes.

## 10. Optional: Use Postman Instead Of Curl

For non-developers or mixed demo audiences:

- create one Postman collection with three folders:
  - `Webchat`
  - `Slack`
  - `Telegram`
- store these Postman variables:
  - `BASE`
  - `WEBCHAT_STREAM_ID`
  - `WEBCHAT_SESSION_ID`
  - `SLACK_SESSION_ID`
  - `TELEGRAM_SESSION_ID`

Helpful note:

- webchat is easiest in Postman because it uses standard JSON plus a simple auth header
- Slack is easiest if a developer first generates the signed payload and then pastes the body and headers into Postman
- Telegram is also straightforward because it uses a static secret-token header in this local demo

## 11. Optional: Switch One Account To Real Transport Mode

After the local fake-mode demo works, you can switch a single account to `real`.

Example Slack real account entry in `.env`:

```text
PYTHON_CLAW_CHANNEL_ACCOUNTS=[
  {
    "channel_account_id":"acct",
    "channel_kind":"slack",
    "mode":"real",
    "outbound_token":"xoxb-your-real-token",
    "signing_secret":"your-real-signing-secret",
    "base_url":"https://slack.com/api"
  },
  {"channel_account_id":"acct","channel_kind":"telegram","mode":"fake"},
  {"channel_account_id":"acct","channel_kind":"webchat","mode":"fake"}
]
```

Keep the same formatting rule here as well:

- use valid JSON
- do not add outer single quotes around the whole `PYTHON_CLAW_CHANNEL_ACCOUNTS` value

If you try real mode:

1. restart the gateway after editing `.env`
2. expose the gateway publicly with your preferred tunnel if the provider must call your local machine
3. point the provider webhook to the correct Spec 012 route
4. keep the worker running locally

Important note:

- real mode validation fails closed if required credentials are missing for that channel kind

## 12. What This Demo Proves

By the end of this walkthrough, you have demonstrated:

- provider-specific gateway routes exist and verify inbound traffic
- Slack and Telegram requests translate into the same canonical backend-owned inbound contract
- webchat now supports production-style inbound plus durable polling
- session routing still stays separate from the transport-address metadata used for outbound delivery
- worker-owned outbound dispatch still creates authoritative delivery rows and attempts
- provider retries and redelivery collapse onto the existing dedupe boundary
- unsupported provider control or event shapes are handled cleanly without polluting transcript state

## 13. Quick Reset Between Demo Runs

If you want a clean local rerun:

1. stop the gateway
2. stop any worker terminals
3. reset the database

Reset commands:

```bash
docker compose --env-file .env down
docker compose --env-file .env up -d
uv run alembic upgrade head
```

If you want a fully clean local database volume as well:

```bash
docker compose --env-file .env down -v
docker compose --env-file .env up -d
uv run alembic upgrade head
```
