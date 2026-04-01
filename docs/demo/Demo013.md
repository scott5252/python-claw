# Demo Guide: Spec 013 Streaming and Real-Time Delivery

This guide shows how to demo the Spec 013 streaming features in a way that works for:

1. a non-developer who wants to see the assistant reply arrive as ordered partial events
2. a developer who wants to verify the durable backend contract behind those events

The demo covers:

1. authenticated webchat inbound for a browser-style client
2. worker-owned execution with delivery-side streaming state
3. webchat SSE replay of ordered stream events
4. continued compatibility with the existing webchat polling surface
5. canonical transcript truth staying in `messages`, not in partial stream rows
6. durable streamed-delivery identity, attempts, and append-only stream events

The demo uses one simple story:

- a customer is chatting with a neighborhood bike shop through the website, and the shop assistant starts replying in visible chunks instead of waiting for one final poll-only message

Important note about this demo:

- this local demo uses fake channel accounts
- the backend still runs the real worker-owned execution flow
- webchat streaming is demonstrated through the new SSE route backed by durable stream-event rows
- the safest local demo uses replayable SSE output over persisted rows
- the existing polling route still works and remains useful as the fallback and replay surface

## 1. What You Will Run

For the main local demo, you will run:

- PostgreSQL with Docker Compose
- database migrations
- the gateway API
- the worker helper
- `curl` commands that simulate a website chat client

You do not need live provider credentials for this demo.

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
PYTHON_CLAW_RUNTIME_STREAMING_ENABLED=true
PYTHON_CLAW_RUNTIME_STREAMING_CHUNK_CHARS=24
PYTHON_CLAW_WEBCHAT_SSE_ENABLED=true
PYTHON_CLAW_WEBCHAT_SSE_REPLAY_LIMIT=100

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

What this means:

- `rule_based` keeps the demo easy to run locally
- runtime streaming is enabled
- webchat SSE is enabled
- fake channel accounts let you exercise the whole backend flow without external services

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

This is important for Spec 013 because the new migration adds:

- streaming-aware outbound delivery metadata
- streaming attempt lifecycle fields
- the append-only `outbound_delivery_stream_events` table

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
INTERNAL='X-Internal-Service-Token: change-me-internal'
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
- `FIRST_SSE_EVENT_ID`
- `FINAL_DELIVERY_ID`

## 6. Main Demo A: Non-Developer Walkthrough

This is the easiest demo path for a mixed audience. It shows:

- a customer message entering through the production-style webchat route
- the worker creating a streamed assistant delivery
- ordered SSE events becoming visible
- polling still showing the final reply
- the transcript still containing one canonical final assistant message

### Scenario

A customer asks the bike shop a long question so the assistant reply is long enough to show multiple streamed chunks.

### Step 1: Submit a webchat message

In Terminal C, run:

```bash
curl -s $BASE/providers/webchat/accounts/acct/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -d '{
    "actor_id": "customer-riley",
    "content": "Hi, can I bring in my commuter bike after 3 PM today for a tune-up and a quick brake check before tomorrow morning?",
    "peer_id": "customer-riley",
    "stream_id": "webchat-stream-riley-013",
    "message_id": "webchat-msg-013-001"
  }'
```

Expected result:

- HTTP `202 Accepted`
- JSON containing `session_id`, `message_id`, `run_id`, `status`, `dedupe_status`, `trace_id`, and `external_message_id`

Write down:

- `WEBCHAT_SESSION_ID`
- `WEBCHAT_RUN_ID`
- `WEBCHAT_STREAM_ID`
  Use `webchat-stream-riley-013`

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
- it should match or include the run from Step 1

What is happening:

1. the worker claims the run
2. the graph prepares the final assistant text
3. the dispatcher creates one logical streamed delivery
4. the dispatcher appends durable stream events
5. the final assistant transcript row is written after the delivery step

### Step 3: Read the streamed reply through SSE

In Terminal C, run:

```bash
curl -N "$BASE/providers/webchat/accounts/acct/stream?stream_id=webchat-stream-riley-013" \
  -H 'X-Webchat-Client-Token: fake-webchat-token'
```

Expected result:

- HTTP `200`
- SSE output with repeated `id:`, `event: delivery`, and `data:` lines
- you should see:
  - one `stream_started` event
  - multiple `text_delta` events
  - one `stream_finalized` event

Example shape:

```text
id: 1
event: delivery
data: {"event_id":1,"delivery_id":1,"attempt_id":1,"sequence_number":1,"event_kind":"stream_started",...}

id: 2
event: delivery
data: {"event_id":2,"delivery_id":1,"attempt_id":1,"sequence_number":2,"event_kind":"text_delta","payload":{"text":"Received: Hi, can I br"}}
```

Write down:

- `FIRST_SSE_EVENT_ID`
  Use the first `id:` value

What this proves:

- the browser-facing contract is SSE
- the assistant reply is exposed as ordered partial events
- the events are replayable because they come from persisted rows

### Step 4: Show the final reply still works through polling

In Terminal C, run:

```bash
curl -s "$BASE/providers/webchat/accounts/acct/poll?stream_id=webchat-stream-riley-013" \
  -H 'X-Webchat-Client-Token: fake-webchat-token'
```

Expected result:

- HTTP `200`
- JSON with `items`
- one item should have:
  - `delivery_kind` equal to `stream_text`
  - `status` equal to `sent`
  - `payload.text` containing the final reply

Write down:

- `FINAL_DELIVERY_ID`
  Use the returned `delivery_id`

What this proves:

- the old webchat polling contract still works
- streaming did not replace the durable completed-delivery replay surface

### Step 5: Show the canonical transcript is still final-only

Replace `replace-with-webchat-session-id` with your real `WEBCHAT_SESSION_ID`, then run:

```bash
curl -s "$BASE/sessions/replace-with-webchat-session-id/messages"
```

Expected result:

- one user message
- one assistant message
- the assistant message contains the full final text
- you do not see partial transcript rows for each delta

What this proves:

- partial output is delivery-side operational state
- `messages` remains the canonical conversation transcript

## 7. Main Demo B: Developer Verification Walkthrough

This section helps a technical audience verify the internal guarantees behind the user-visible demo.

### Step 1: Prove SSE replay is cursor-safe

Replace `replace-with-first-sse-event-id` with your real `FIRST_SSE_EVENT_ID`, then run:

```bash
curl -N "$BASE/providers/webchat/accounts/acct/stream?stream_id=webchat-stream-riley-013" \
  -H 'X-Webchat-Client-Token: fake-webchat-token' \
  -H "Last-Event-ID: replace-with-first-sse-event-id"
```

Expected result:

- the replay starts after the earlier cursor
- you should not get the original first event again
- you should still get later `text_delta` or `stream_finalized` events if they exist after that cursor

This demonstrates:

- replay uses a durable monotonic event id
- reconnect is cursor-based
- the endpoint is reading persisted rows, not worker-local memory

### Step 2: Inspect delivery diagnostics

Run:

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Look for:

- the `webchat` delivery row
- `status` equal to `sent`
- `provider_metadata.transport_mode` equal to `sse`
- `payload.streaming` equal to `true`
- the bounded payload preview

This demonstrates:

- streaming still reconciles into the normal delivery reporting surface

### Step 3: Query the database for streamed delivery identity and attempts

In Terminal C, set these variables:

```bash
export DEMO_STREAM_ID=webchat-stream-riley-013
export DEMO_ACCOUNT_ID=acct
```

Then run:

```bash
uv run python - <<'PY'
import json
import os
from sqlalchemy import select

from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.db.models import (
    SessionRecord,
    OutboundDeliveryRecord,
    OutboundDeliveryAttemptRecord,
    OutboundDeliveryStreamEventRecord,
)

settings = Settings()
manager = DatabaseSessionManager(settings.database_url)

stream_id = os.environ["DEMO_STREAM_ID"]
account_id = os.environ["DEMO_ACCOUNT_ID"]

with manager.session() as db:
    session = db.scalar(
        select(SessionRecord).where(
            SessionRecord.channel_kind == "webchat",
            SessionRecord.channel_account_id == account_id,
            SessionRecord.transport_address_key == stream_id,
        )
    )
    if session is None:
        raise SystemExit("session not found")

    deliveries = list(
        db.scalars(
            select(OutboundDeliveryRecord)
            .where(OutboundDeliveryRecord.session_id == session.id)
            .order_by(OutboundDeliveryRecord.id.asc())
        )
    )
    attempts = list(
        db.scalars(
            select(OutboundDeliveryAttemptRecord)
            .where(
                OutboundDeliveryAttemptRecord.outbound_delivery_id == deliveries[-1].id
            )
            .order_by(OutboundDeliveryAttemptRecord.attempt_number.asc())
        )
    )
    events = list(
        db.scalars(
            select(OutboundDeliveryStreamEventRecord)
            .where(
                OutboundDeliveryStreamEventRecord.outbound_delivery_id == deliveries[-1].id
            )
            .order_by(
                OutboundDeliveryStreamEventRecord.outbound_delivery_attempt_id.asc(),
                OutboundDeliveryStreamEventRecord.sequence_number.asc(),
            )
        )
    )

    print("session_id:", session.id)
    print("delivery_count:", len(deliveries))
    print("latest_delivery:", {
        "id": deliveries[-1].id,
        "delivery_kind": deliveries[-1].delivery_kind,
        "status": deliveries[-1].status,
        "completion_status": deliveries[-1].completion_status,
    })
    print("attempts:", [
        {
            "id": attempt.id,
            "attempt_number": attempt.attempt_number,
            "status": attempt.status,
            "stream_status": attempt.stream_status,
            "last_sequence_number": attempt.last_sequence_number,
            "completion_reason": attempt.completion_reason,
        }
        for attempt in attempts
    ])
    print("events:", [
        {
            "event_id": event.id,
            "attempt_id": event.outbound_delivery_attempt_id,
            "sequence_number": event.sequence_number,
            "event_kind": event.event_kind,
            "payload": json.loads(event.payload_json),
        }
        for event in events
    ])
PY
```

Expected result:

- one logical streamed delivery for the assistant response
- one attempt for the successful path
- ordered append-only stream events with increasing sequence numbers

This demonstrates:

- delivery identity is stable
- attempts are separate from the delivery row
- stream events are append-only children of an attempt

### Step 4: Prove the transcript stayed separate from partial delivery

Run:

```bash
uv run python - <<'PY'
import os
from sqlalchemy import select

from src.config.settings import Settings
from src.db.session import DatabaseSessionManager
from src.db.models import MessageRecord, SessionRecord

settings = Settings()
manager = DatabaseSessionManager(settings.database_url)

stream_id = os.environ["DEMO_STREAM_ID"]
account_id = os.environ["DEMO_ACCOUNT_ID"]

with manager.session() as db:
    session = db.scalar(
        select(SessionRecord).where(
            SessionRecord.channel_kind == "webchat",
            SessionRecord.channel_account_id == account_id,
            SessionRecord.transport_address_key == stream_id,
        )
    )
    messages = list(
        db.scalars(
            select(MessageRecord)
            .where(MessageRecord.session_id == session.id)
            .order_by(MessageRecord.id.asc())
        )
    )
    print([
        {"id": message.id, "role": message.role, "content": message.content}
        for message in messages
    ])
PY
```

Expected result:

- exactly one user row for the inbound message
- exactly one assistant row for the completed reply
- no partial assistant rows

This demonstrates:

- Spec 013 kept transcript truth append-only and final-only

## 8. Optional: Show Unsupported Channels Still Use Whole-Message Delivery

This quick check is useful for a developer audience.

Run the Slack or Telegram demo from [Demo012.md](/docs/demo/Demo012.md).

What you should observe:

- Slack and Telegram still use the existing whole-message path
- Spec 013 is additive
- webchat gained the SSE surface without creating a second runtime path

## 9. What This Demo Proves

By the end of this walkthrough, you have demonstrated:

- webchat now has an authenticated SSE read surface
- assistant output can be observed as ordered partial events
- partial output is durable delivery state, not transcript truth
- polling still works as the completed-reply replay surface
- the worker still owns run execution and final transcript persistence
- streamed responses use one logical delivery identity plus attempts and stream events
- reconnect and replay work through durable event ids

## 10. Quick Troubleshooting

If the SSE route returns no events:

1. make sure you already ran the worker command in Terminal B
2. make sure the `stream_id` in the SSE URL exactly matches the `stream_id` used in the inbound webchat request
3. make sure you sent the `X-Webchat-Client-Token: fake-webchat-token` header
4. make sure `PYTHON_CLAW_RUNTIME_STREAMING_ENABLED=true` and `PYTHON_CLAW_WEBCHAT_SSE_ENABLED=true` are present in `.env`

If polling works but SSE is empty:

- check that the inbound request was for `channel_kind=webchat`
- check that migrations were applied through `uv run alembic upgrade head`
- rerun the developer database query in Section 7 to confirm whether stream events were persisted

## 11. Quick Reset Between Demo Runs

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
