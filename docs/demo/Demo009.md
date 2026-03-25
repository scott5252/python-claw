# Demo Guide: Spec 009 Provider-Backed LLM Runtime

This guide shows a junior technical person how to:

1. Set up the application for provider-backed LLM execution
2. Run the application in a way that exercises the real provider path
3. Demonstrate a complete, successful natural-language chat flow
4. Demonstrate an LLM-suggested approval-gated tool request safely
5. Verify that the backend still owns approvals, execution, persistence, and diagnostics

The demo uses a real-world scenario:

- a bicycle repair shop employee uses normal language to ask the assistant for customer communication help

This is a good demo because it shows the main Spec 009 behaviors:

- provider-backed natural-language replies
- backend-owned prompt assembly
- LLM-suggested tool requests translated into backend contracts
- approval-safe governed tool handling
- append-only transcript and manifest persistence
- worker-owned execution and operator diagnostics

Important note about the current implementation:

- the repository now supports a real provider-backed LLM path
- the default runtime mode is still `rule_based` for safety in local development and CI
- you must explicitly enable `PYTHON_CLAW_RUNTIME_MODE=provider`
- tool execution is still backend-owned
- approval-gated actions still require exact backend approval before execution
- outbound channel adapters are still thin local implementations, so this demo proves the runtime and persistence path, not a production transport integration

## 1. What You Will Run

For a successful local demo, you will run:

- PostgreSQL and Redis with Docker Compose
- database migrations
- the gateway API
- the local one-pass worker helper
- a real provider-backed model call through the gateway and worker path

You do not need the node runner for this demo.

## 2. Before You Start

You need:

- Python 3.11+
- `uv`
- Docker Desktop or another Docker runtime
- a valid OpenAI API key or another compatible endpoint that works with the current provider adapter settings

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

PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_PROVIDER=openai
PYTHON_CLAW_LLM_API_KEY=replace-with-your-real-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
PYTHON_CLAW_LLM_TIMEOUT_SECONDS=30
PYTHON_CLAW_LLM_MAX_RETRIES=1
PYTHON_CLAW_LLM_TEMPERATURE=0.2
PYTHON_CLAW_LLM_MAX_OUTPUT_TOKENS=512
PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto
PYTHON_CLAW_LLM_MAX_TOOL_REQUESTS_PER_TURN=4
PYTHON_CLAW_LLM_DISABLE_TOOLS=false
```

Optional if you use an OpenAI-compatible endpoint instead of the default API URL:

```text
PYTHON_CLAW_LLM_BASE_URL=https://your-compatible-endpoint.example/v1
```

What is happening in the system:

- the app loads configuration from `.env`
- `PYTHON_CLAW_RUNTIME_MODE=provider` tells the gateway dependency wiring to build the provider-backed adapter instead of the rule-based adapter
- `PYTHON_CLAW_LLM_API_KEY` is required in provider mode
- `PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto` allows the backend to expose visible tools to the model
- `PYTHON_CLAW_LLM_DISABLE_TOOLS=false` keeps tool suggestions enabled for the governed-tool portion of the demo
- the diagnostics tokens protect `/health/ready` and `/diagnostics/*`

Important fail-closed behavior:

- if provider mode is selected and `PYTHON_CLAW_LLM_API_KEY` is missing, startup fails clearly
- the system does not silently fall back to the rule-based adapter

### Step 2: Install Python dependencies

Run:

```bash
uv sync --group dev
```

What is happening in the system:

- `uv` creates or updates the local virtual environment
- Python packages needed by the gateway, worker, SQLAlchemy, FastAPI, Alembic, tests, and the provider SDK are installed

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

- PostgreSQL starts and becomes the durable store for sessions, messages, runs, approvals, artifacts, manifests, and diagnostics
- Redis also starts because it is part of the local development stack, even though this demo path does not depend on it directly

### Step 4: Apply the database schema

Run:

```bash
uv run alembic upgrade head
```

What is happening in the system:

- Alembic creates all current tables through Spec 009
- after this step, the gateway can persist inbound messages and the worker can process queued runs through the provider-backed runtime path

## 4. Run The Application

Use three terminals for the main demo.

### Terminal A: Start the gateway API

Run:

```bash
uv run uvicorn apps.gateway.main:app --reload
```

What is happening in the system:

- FastAPI starts on `http://127.0.0.1:8000`
- the app builds shared services for sessions, execution runs, health, diagnostics, and the provider-backed model adapter
- if the provider settings are invalid, startup fails now rather than on the first user message

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
- it assembles transcript context and backend-owned prompt data
- it invokes the provider-backed runtime
- it executes any approved tool request through the normal graph path
- it commits and exits

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

Expected result:

- HTTP 200
- a PostgreSQL check with status `ok`

What is happening in the system:

- `/health/live` only checks that the process is running
- `/health/ready` also checks that the app can talk to PostgreSQL and that the application can finish startup in the selected runtime mode

## Main Demo

This section is the primary end-to-end demo for most audiences. It shows a real provider-backed natural-language reply first, then an LLM-suggested governed action that still requires backend approval.

### Scenario

A shop employee is working in a support conversation with customer Maya.

We will demonstrate four turns:

1. The employee asks a normal natural-language question and gets a provider-backed assistant reply.
2. The employee asks the assistant to contact the customer in ordinary language.
3. The model suggests a governed outbound action, but the backend creates a proposal instead of executing it.
4. The employee approves the proposal and then retries the request.
5. The approved outbound action is executed through the normal backend-owned tool and dispatcher flow.

This is a real-world workflow because it shows both everyday conversational use and the controlled path for externally impactful actions.

## Part A: Prove The LLM Path Is Active

### Step 1: Submit a normal natural-language user message

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo009-msg-1",
    "sender_id": "employee-alex",
    "content": "A customer says her bike still clicks when pedaling after a tune-up. Give me a short, professional reply I can send back and include one follow-up question.",
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
2. It checks `inbound_dedupe` to make sure `demo009-msg-1` has not already been processed.
3. It resolves or creates a session for this direct conversation.
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
2. It assembles transcript context through `ContextService`.
3. It builds a typed backend-owned prompt payload with system instructions, conversation items, attachments, visible tools, approval guidance, response contract, and metadata.
4. The provider-backed model adapter serializes that prompt payload and calls the configured provider.
5. The provider returns a natural-language answer.
6. The graph appends the assistant message to `messages`.
7. The worker persists a `context_manifests` row that includes bounded model-execution metadata.
8. The worker completes the run.

Troubleshooting note for provider rate limits:

- If the run fails with an error like `provider rate limited`, the request did reach the real provider path, but the provider rejected it with a quota or rate-limit response.
- The current implementation now uses bounded retry backoff with jitter for retryable provider failures, so one `429` should no longer trigger an immediate tight retry loop.
- The most useful worker log fields to inspect are `event_name`, `error`, `failure_category`, `execution_run_id`, and `trace_id`.
- A provider-side throttle will usually appear as `event_name="execution_run.failed"` with `error` containing `provider rate limited` and `failure_category` mapped to a dependency/provider failure instead of a generic internal error.
- If this happens repeatedly, check `PYTHON_CLAW_LLM_API_KEY`, project billing or quota, model access for `PYTHON_CLAW_LLM_MODEL`, and any custom `PYTHON_CLAW_LLM_BASE_URL` proxy or compatible endpoint.

### Step 3: Read the chat transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=10
```

Replace `<SESSION_ID>` with the `session_id` from the first response.

Expected result:

- two messages in order
- the first is the original user message
- the second is a natural-language assistant reply that is not `Received: ...`

What success looks like:

- the response should read like a real assistant reply
- it should be specific to the bike-repair scenario
- it should include a follow-up question because that was requested

This is the easiest proof that provider-backed mode is active.

### Step 4: Inspect run diagnostics for provider metadata

In Terminal C, run:

```bash
curl -s $BASE/runs/<RUN_ID>
```

Then run:

```bash
curl -s $BASE/diagnostics/runs/<RUN_ID> -H "$AUTH"
```

Expected result:

- the run is `completed`
- diagnostics show the same durable run record

Then inspect continuity diagnostics:

```bash
curl -s $BASE/diagnostics/sessions/<SESSION_ID>/continuity -H "$AUTH"
```

Expected result:

- the session continuity response includes a recent manifest
- that manifest should reflect the provider-backed execution path for this turn

What is happening in the system:

- bounded provider execution metadata is persisted through the graph-owned manifest path
- diagnostics read durable state rather than a separate inference-history system

## Part B: Demonstrate LLM-Suggested Governed Action Handling

This section shows the most important Spec 009 safety behavior: the model can suggest a governed tool, but the backend remains authoritative.

### Step 5: Ask for a customer notification in normal language

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo009-msg-2",
    "sender_id": "employee-alex",
    "content": "Please let Maya know that bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- same `session_id` as before
- a new `message_id`
- a new `run_id`

### Step 6: Process the queued run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the new run.
2. The graph assembles context and prompt data.
3. The provider-backed model may decide that `send_message` is the right tool for the request.
4. The model adapter translates the provider tool suggestion into a backend-owned `ToolRequest`.
5. The graph checks policy and approvals before any tool execution.
6. Because `send_message` is governed and no exact active approval exists yet, the tool is not executed.
7. Instead, the graph creates a governance proposal through the existing approval lifecycle.
8. The graph appends an assistant message telling the user how to approve the proposal.
9. The worker persists the new context manifest and completes the run.

### Step 7: Read the transcript and pending approval

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=20
```

Expected result:

- a new assistant message tells the user that approval is required
- it includes a `proposal_id` and an `approve <proposal_id>` instruction

Now read the pending approval queue:

```bash
curl -s $BASE/sessions/<SESSION_ID>/governance/pending
```

Expected result:

- one pending proposal
- `capability_name` should be `send_message`
- `typed_action_id` should be `tool.send_message`
- the canonical parameters should contain the message text to Maya

Write down the `proposal_id`.

Important Spec 009 point:

- on this LLM-originated governed path, the proposal is the canonical requested-action record
- the backend does not create a competing `tool_proposal` artifact before approval

## Part C: Approve And Retry The Governed Request

### Step 8: Submit the approval message

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo009-msg-3",
    "sender_id": "employee-alex",
    "content": "approve <PROPOSAL_ID>",
    "peer_id": "customer-maya"
  }'
```

Replace `<PROPOSAL_ID>` with the value from the pending approval response.

Expected result:

- HTTP 202
- same `session_id`
- a new `run_id`

### Step 9: Process the approval run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the new run.
2. The graph classifies the message as a deterministic approval decision before asking the model to interpret it.
3. It creates or updates `resource_approvals`, `active_resources`, and governance audit state.
4. It appends an assistant confirmation message.
5. It writes a new context manifest and completes the run.

### Step 10: Retry the original request in normal language

In Terminal C, run:

```bash
curl -s $BASE/inbound/message \
  -H 'Content-Type: application/json' \
  -d '{
    "channel_kind": "webchat",
    "channel_account_id": "bike-shop-demo",
    "external_message_id": "demo009-msg-4",
    "sender_id": "employee-alex",
    "content": "Please let Maya know that bike repair order BR-1042 is complete and ready for pickup today before 6 PM.",
    "peer_id": "customer-maya"
  }'
```

Expected result:

- HTTP 202
- same `session_id`
- a new `run_id`

### Step 11: Process the approved send run

In Terminal B, run the worker helper again:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

What is happening in the system:

1. The worker claims the run.
2. The provider-backed model again suggests the customer-notification action.
3. The graph translates the model suggestion into a backend-owned `ToolRequest`.
4. The backend checks approval and finds an exact active match.
5. The `send_message` tool runs through the normal backend-owned execution path.
6. The graph appends tool artifacts, tool audit events, and an assistant message.
7. After the graph completes, the dispatcher creates outbound delivery records.
8. The local `webchat` adapter returns a synthetic success result, so the delivery is marked `sent`.
9. The run is marked `completed`.

### Step 12: Read the final transcript

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/messages?limit=30
```

Expected result:

- the transcript includes:
  - the original natural-language question
  - the provider-backed answer
  - the governed send request
  - the approval message
  - the final successful send turn
- the newest assistant reply should be similar to:

```text
Prepared outbound message: Hello Maya, your bike repair order BR-1042 is complete and ready for pickup today before 6 PM.
```

## Part D: Show The Durable Evidence

### Step 13: Show all runs for the session

In Terminal C, run:

```bash
curl -s $BASE/sessions/<SESSION_ID>/runs
```

Expected result:

- four runs for the four inbound messages
- each run should be `completed`

### Step 14: Show diagnostics for deliveries

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/deliveries -H "$AUTH"
```

Expected result:

- one delivery row for the successful approved send path
- status `sent`

### Step 15: Show continuity diagnostics for the session

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/sessions/<SESSION_ID>/continuity -H "$AUTH"
```

Expected result:

- recent manifests exist for the session
- the latest manifest reflects the successful provider-backed turn
- the manifest trail proves the context and execution metadata were persisted on the normal backend-owned path

### Step 16: Show overall run diagnostics

In Terminal C, run:

```bash
curl -s $BASE/diagnostics/runs -H "$AUTH"
```

Expected result:

- you see the accepted and completed runs
- the operator diagnostics layer is reading the same durable run records the worker updated

## 5. Why This Demo Matters

This demo proves the most important Spec 009 outcomes:

- normal user text can produce a real provider-backed assistant reply
- prompt construction stays backend-owned
- deterministic approval commands still bypass model interpretation
- provider-suggested tool use is translated into existing backend contracts
- governed tool requests do not execute without exact approval
- approved governed requests still execute through the existing graph and dispatcher boundaries
- manifests and diagnostics stay append-only and operator-readable

## 6. Common Mistakes And Fixes

### Mistake: the gateway fails to start in provider mode

Most likely causes:

- `PYTHON_CLAW_RUNTIME_MODE=provider` is set but `PYTHON_CLAW_LLM_API_KEY` is missing
- `PYTHON_CLAW_LLM_MODEL` is empty or invalid
- dependencies were not installed after the provider SDK was added

Fix:

```bash
uv sync --group dev
```

Then confirm `.env` includes:

```text
PYTHON_CLAW_RUNTIME_MODE=provider
PYTHON_CLAW_LLM_API_KEY=your-real-key
PYTHON_CLAW_LLM_MODEL=gpt-4o-mini
```

### Mistake: posting to `/inbound/message` returns 202 but no assistant reply appears

Cause:

- the gateway only queued the work
- the worker pass has not been run yet

Fix:

```bash
uv run python - <<'PY'
from apps.worker.jobs import run_once
print(run_once())
PY
```

### Mistake: the reply still looks rule-based

Symptoms:

- the assistant says `Received: ...`

Cause:

- the app is still running in `rule_based` mode
- or the gateway was not restarted after updating `.env`

Fix:

1. Confirm `.env` contains `PYTHON_CLAW_RUNTIME_MODE=provider`
2. Confirm `PYTHON_CLAW_LLM_API_KEY` is set
3. Restart the gateway

### Mistake: the governed send request does not create a proposal

Possible cause:

- the model produced plain text instead of a tool suggestion on that turn

What to do:

- try slightly more explicit wording such as:

```text
Please send Maya a message saying bike repair order BR-1042 is complete and ready for pickup today before 6 PM.
```

- keep `PYTHON_CLAW_LLM_TOOL_CALL_MODE=auto`
- keep `PYTHON_CLAW_LLM_DISABLE_TOOLS=false`

### Mistake: `/health/ready` or `/diagnostics/*` returns 401

Cause:

- the operator authorization header is missing or incorrect

Fix:

```bash
curl $BASE/health/ready -H 'Authorization: Bearer change-me'
```

## 7. Success Checklist

By the end of the demo, you should be able to confirm:

```text
[ ] .env is present and includes provider and diagnostics settings
[ ] uv sync --group dev completed successfully
[ ] docker compose --env-file .env up -d completed successfully
[ ] uv run alembic upgrade head completed successfully
[ ] the gateway starts successfully in provider mode
[ ] /health/live returns 200
[ ] /health/ready returns 200 with Authorization header
[ ] the first natural-language turn produces a non-rule-based assistant answer
[ ] run and continuity diagnostics show the provider-backed turn completed
[ ] the natural-language customer-notification request creates a governance proposal
[ ] approve <proposal_id> activates the governed action
[ ] retrying the same request produces Prepared outbound message: ...
[ ] diagnostics/deliveries shows a sent delivery
```

If all of those are true, you have successfully demonstrated Spec 009 in a realistic end-to-end workflow.
